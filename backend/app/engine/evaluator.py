"""Answer evaluation: model judgement, validated and grounded.

The model returns a rubric record; this module refuses to trust it blindly.
Scores are coerced into range, the evidence quote is verified against the real
answer, and a cheap rule-based contradiction check runs against earlier claims.
The result is an ``AnswerEvaluation`` that is always well-formed, whatever the
model did.
"""

from __future__ import annotations

import logging
import re

from ..data.curriculum import get_curriculum, tokenize
from ..llm.json_repair import coerce_float, coerce_int, coerce_str_list, coerce_text
from ..llm.router import LLMRouter
from ..llm.schemas import ANSWER_EVALUATION_SCHEMA
from ..models.domain import (
    AnswerEvaluation,
    Claim,
    ClaimStatus,
    DimensionScores,
    InterviewState,
)
from . import prompts
from .grounding import verify_quote

log = logging.getLogger("cohortiq.evaluator")

_VALID_VERDICTS = {"strong", "adequate", "weak", "non_answer"}
_VALID_FLAGS = {
    "vague_language", "buzzword_heavy", "rambling", "too_short", "no_concrete_metrics",
    "possibly_off_topic", "memorised_sounding", "contradicts_earlier", "overclaiming",
    "non_answer",
}
_NEGATION = re.compile(r"\b(not|never|no|didn'?t|don'?t|without|couldn'?t|failed to)\b", re.I)


async def evaluate_answer(
    *,
    router: LLMRouter,
    state: InterviewState,
    question: str,
    answer: str,
    difficulty: int,
) -> tuple[AnswerEvaluation, list[str]]:
    """Score one answer. Returns (evaluation, router notes)."""
    slot = state.active_slot
    day = get_curriculum().day(slot.day) if slot else None
    prior_claims = [c.text for c in state.claims]

    routed = await router.structured(
        system=prompts.EVALUATOR_SYSTEM,
        user=prompts.evaluator_user(
            question=question,
            answer=answer,
            day=day,
            slot=slot,
            prior_claims=prior_claims,
            difficulty=difficulty,
        ),
        schema=ANSWER_EVALUATION_SCHEMA,
        schema_name="answer_evaluation",
        context={
            "answer": answer,
            "question": question,
            "day": slot.day if slot else None,
            "difficulty": difficulty,
        },
        max_tokens=800,
        temperature=0.1,  # scoring should be as stable as the model allows
    )

    evaluation = _normalise(routed.data, answer=answer, source=routed.provider)
    _apply_contradiction_check(evaluation, state, answer)
    return evaluation, routed.notes


def _normalise(data: dict, *, answer: str, source: str) -> AnswerEvaluation:
    raw_scores = data.get("scores")
    if not isinstance(raw_scores, dict):
        raw_scores = {}

    scores = DimensionScores(
        technical_accuracy=coerce_int(raw_scores.get("technical_accuracy"), 50),
        conceptual_depth=coerce_int(raw_scores.get("conceptual_depth"), 50),
        specificity=coerce_int(raw_scores.get("specificity"), 50),
        communication=coerce_int(raw_scores.get("communication"), 50),
        practical_evidence=coerce_int(raw_scores.get("practical_evidence"), 50),
        relevance=coerce_int(raw_scores.get("relevance"), 50),
    )

    verdict = coerce_text(data.get("verdict"), "adequate").lower()
    if verdict not in _VALID_VERDICTS:
        composite = scores.composite()
        verdict = "strong" if composite >= 72 else "adequate" if composite >= 52 else "weak"

    flags = [f for f in coerce_str_list(data.get("flags"), limit=8) if f in _VALID_FLAGS]

    quote_ok, quote = verify_quote(coerce_text(data.get("evidence_quote"), "", 400), answer)
    if not quote_ok:
        flags.append("ungrounded_quote_removed") if "ungrounded_quote_removed" not in flags else None
        log.info("evaluator quote failed grounding check; dropped")

    evaluation = AnswerEvaluation(
        scores=scores,
        verdict=verdict,  # type: ignore[arg-type]
        rationale=coerce_text(data.get("rationale"), "No rationale returned.", 600),
        evidence_quote=quote,
        missing_points=coerce_str_list(data.get("missing_points"), limit=4),
        claims=coerce_str_list(data.get("claims"), limit=5),
        flags=flags,
        followup_hook=coerce_text(data.get("followup_hook"), "", 300),
        confidence=coerce_float(data.get("confidence"), 0.5),
        source=source,
    )

    # A non_answer verdict with high scores is incoherent; trust the verdict.
    if evaluation.verdict == "non_answer" and evaluation.composite > 25:
        evaluation.scores = DimensionScores(
            technical_accuracy=0, conceptual_depth=0, specificity=0,
            communication=15, practical_evidence=0, relevance=0,
        )
    return evaluation


def _apply_contradiction_check(
    evaluation: AnswerEvaluation, state: InterviewState, answer: str
) -> None:
    """Cheap lexical contradiction detection against earlier claims.

    Deliberately conservative: it only fires when the same distinctive terms
    recur with opposite polarity. False accusations of lying are far worse than
    a missed contradiction.
    """
    answer_tokens = set(tokenize(answer))
    if not answer_tokens:
        return
    answer_negated = bool(_NEGATION.search(answer))

    for claim in state.claims:
        claim_tokens = set(tokenize(claim.text))
        if len(claim_tokens) < 4:
            continue
        overlap = claim_tokens & answer_tokens
        if len(overlap) / len(claim_tokens) < 0.5:
            continue
        claim_negated = bool(_NEGATION.search(claim.text))
        if claim_negated != answer_negated:
            if "contradicts_earlier" not in evaluation.flags:
                evaluation.flags.append("contradicts_earlier")
            claim.status = ClaimStatus.CONTRADICTED
            claim.evidence.append(answer[:200])
            return


def record_claims(state: InterviewState, evaluation: AnswerEvaluation, turn_index: int) -> None:
    """Append new claims to the ledger, deduplicating against what is there."""
    slot = state.active_slot
    topic = slot.day_title if slot else "general"
    existing = {c.text.lower()[:80] for c in state.claims}
    for text in evaluation.claims:
        key = text.lower()[:80]
        if key in existing or len(text) < 12:
            continue
        existing.add(key)
        state.claims.append(
            Claim(
                claim_id=f"C{len(state.claims)}",
                text=text,
                topic=topic,
                turn_index=turn_index,
                status=ClaimStatus.ASSERTED,
            )
        )


def mark_claim_probed(state: InterviewState, hook: str) -> None:
    if not hook:
        return
    hook_tokens = set(tokenize(hook))
    if not hook_tokens:
        return
    for claim in state.claims:
        if claim.status is not ClaimStatus.ASSERTED:
            continue
        claim_tokens = set(tokenize(claim.text))
        if claim_tokens and len(claim_tokens & hook_tokens) / len(claim_tokens) >= 0.4:
            claim.status = ClaimStatus.PROBED
            return


def resolve_claim_outcome(state: InterviewState, evaluation: AnswerEvaluation) -> None:
    """After a probe, decide whether the probed claim held up."""
    for claim in state.claims:
        if claim.status is not ClaimStatus.PROBED:
            continue
        if evaluation.verdict in ("strong", "adequate") and evaluation.scores.specificity >= 55:
            claim.status = ClaimStatus.SUBSTANTIATED
            if evaluation.evidence_quote:
                claim.evidence.append(evaluation.evidence_quote)
        elif evaluation.verdict in ("weak", "non_answer"):
            claim.status = ClaimStatus.UNSUPPORTED
        return
