"""Final assessment.

Two artefacts come out of here:

* ``feedback`` — exactly the four fields the technical spec requires.
* ``report``  — the richer evidence pack our dashboard renders (per-topic
  scores, dimension averages, the interview replay timeline, the claim ledger).

The model only ever sees the evidence pack. It cannot see the raw transcript,
which means it cannot quote something the candidate never said, and every
number in the dashboard is computed in Python rather than generated.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..llm.json_repair import coerce_str_list, coerce_text
from ..llm.router import LLMRouter
from ..llm.schemas import FINAL_REPORT_SCHEMA
from ..models.contract import Feedback
from ..models.domain import ClaimStatus, InterviewState, Turn
from . import prompts
from .grounding import check_report

_DIMENSIONS = (
    "technical_accuracy", "conceptual_depth", "specificity",
    "communication", "practical_evidence", "relevance",
)

_READINESS_BANDS = (
    (80, "Interview ready", "Can defend their cohort work under senior questioning."),
    (65, "Nearly ready", "Solid grasp; needs sharper specifics under follow-up."),
    (50, "Developing", "Understands the outline, thin on mechanism and evidence."),
    (0, "Early", "Needs to rebuild and narrate the core exercises before interviewing."),
)


def build_evidence(state: InterviewState) -> dict[str, Any]:
    """Everything measurable about the interview. Pure computation, no model."""
    answered = state.answered_turns()

    by_slot: dict[str, list[Turn]] = defaultdict(list)
    for turn in answered:
        if turn.slot_id:
            by_slot[turn.slot_id].append(turn)

    per_topic: list[dict[str, Any]] = []
    for slot in state.plan:
        turns = by_slot.get(slot.slot_id, [])
        if not turns:
            continue
        scores = [t.evaluation.composite for t in turns if t.evaluation]
        flags = sorted({f for t in turns if t.evaluation for f in t.evaluation.flags})
        per_topic.append(
            {
                "slotId": slot.slot_id,
                "day": slot.day,
                "topic": slot.day_title,
                "module": slot.module,
                "kind": slot.kind.value,
                "signal": slot.signal,
                "signalCode": slot.signal_code,
                "score": int(sum(scores) / len(scores)) if scores else 0,
                "questions": len(turns),
                "flags": flags,
            }
        )

    dimension_totals: dict[str, list[int]] = {d: [] for d in _DIMENSIONS}
    for turn in answered:
        if not turn.evaluation:
            continue
        for dim in _DIMENSIONS:
            dimension_totals[dim].append(getattr(turn.evaluation.scores, dim))
    dimension_averages = {
        d: int(sum(v) / len(v)) if v else 0 for d, v in dimension_totals.items()
    }

    composites = [t.evaluation.composite for t in answered if t.evaluation]
    overall = int(sum(composites) / len(composites)) if composites else 0

    quotes: list[dict[str, Any]] = []
    for turn in answered:
        ev = turn.evaluation
        if not ev or not ev.evidence_quote:
            continue
        quotes.append(
            {
                "day": turn.day,
                "label": ev.verdict,
                "text": ev.evidence_quote[:280],
                "turn": turn.index,
            }
        )

    missing_points: list[str] = []
    for turn in answered:
        if turn.evaluation:
            for point in turn.evaluation.missing_points:
                if point not in missing_points:
                    missing_points.append(point)

    behaviours = _behaviour_notes(state)

    return {
        "per_topic": per_topic,
        "dimension_averages": dimension_averages,
        "overall": overall,
        "questions": state.questions_asked,
        "days": len(state.covered_days()),
        "quotes": quotes,
        "missing_points": missing_points,
        "behaviours": behaviours,
        "name": state.candidate.name,
    }


def _behaviour_notes(state: InterviewState) -> list[str]:
    notes: list[str] = []
    non_answers = sum(
        1 for t in state.turns if t.utterance and t.utterance.value in {"DONT_KNOW", "EMPTY", "REQUEST_SKIP"}
    )
    if non_answers:
        notes.append(f"{non_answers} question(s) were skipped or answered with 'I don't know'")
    if state.injection_attempts:
        notes.append(
            f"{state.injection_attempts} attempt(s) to instruct the interviewer were detected and ignored"
        )
    hints = sum(1 for t in state.turns if t.utterance and t.utterance.value == "REQUEST_HINT")
    if hints:
        notes.append(f"asked for a hint {hints} time(s)")
    contradicted = [c for c in state.claims if c.status is ClaimStatus.CONTRADICTED]
    if contradicted:
        notes.append(f"{len(contradicted)} statement(s) conflicted with something said earlier")
    unsupported = [c for c in state.claims if c.status is ClaimStatus.UNSUPPORTED]
    if unsupported:
        notes.append(f"{len(unsupported)} claim(s) did not hold up when probed")
    substantiated = [c for c in state.claims if c.status is ClaimStatus.SUBSTANTIATED]
    if substantiated:
        notes.append(f"{len(substantiated)} claim(s) were backed with specifics when challenged")
    lengths = [len(t.text.split()) for t in state.turns if t.role == "candidate"]
    # 20 words is roughly two spoken sentences — below that the candidate is
    # genuinely terse rather than merely efficient.
    if lengths and sum(lengths) / len(lengths) < 20:
        notes.append("answers were consistently short (average under 20 words)")
    return notes


def build_timeline(state: InterviewState) -> list[dict[str, Any]]:
    """Interview replay: every question, its trigger, and how it landed."""
    timeline: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    for turn in state.turns:
        if turn.role == "interviewer":
            pending = {
                "turn": turn.index,
                "question": turn.text,
                "day": turn.day,
                "action": turn.action.value if turn.action else None,
                "difficulty": turn.difficulty,
                "reasonCode": (turn.trace or {}).get("reasonCode"),
                "why": (turn.trace or {}).get("why"),
            }
            timeline.append(pending)
        elif turn.role == "candidate" and pending is not None:
            ev = turn.evaluation
            pending["answer"] = turn.text[:600]
            pending["utterance"] = turn.utterance.value if turn.utterance else None
            if ev:
                pending["score"] = ev.composite
                pending["verdict"] = ev.verdict
                pending["flags"] = ev.flags
                pending["rationale"] = ev.rationale
                pending["dimensions"] = ev.scores.as_dict()
            pending = None
    return timeline


def readiness_band(score: int) -> dict[str, str]:
    for threshold, label, note in _READINESS_BANDS:
        if score >= threshold:
            return {"label": label, "note": note}
    return {"label": "Early", "note": ""}


async def generate_report(
    *, router: LLMRouter, state: InterviewState
) -> tuple[Feedback, dict[str, Any], list[str]]:
    evidence = build_evidence(state)

    routed = await router.structured(
        system=prompts.REPORT_SYSTEM,
        user=prompts.report_user(state, evidence),
        schema=FINAL_REPORT_SCHEMA,
        schema_name="final_report",
        context=evidence,
        max_tokens=1100,
        temperature=0.35,
    )

    raw = routed.data
    # The vocabulary a grounded report may draw on: the transcript, the topics
    # covered, unmet objectives, and the candidate's own identity fields (their
    # surname is legitimate in a report even if they never said it out loud).
    transcript_texts = (
        [t.text for t in state.turns]
        + [t["topic"] for t in evidence["per_topic"]]
        + [t["module"] for t in evidence["per_topic"]]
        + evidence["missing_points"]
        + [state.candidate.name, state.candidate.job_role, state.candidate.education]
    )
    _, warnings = check_report(raw, transcript_texts)

    feedback = Feedback(
        summary=coerce_text(raw.get("summary"), _fallback_summary(evidence), 2000),
        strengths=coerce_str_list(raw.get("strengths"), limit=5) or _fallback_strengths(evidence),
        gaps=coerce_str_list(raw.get("gaps"), limit=5) or _fallback_gaps(evidence),
        next=coerce_str_list(raw.get("next"), limit=5) or _fallback_next(evidence),
    )

    report = {
        "overall": evidence["overall"],
        "readiness": readiness_band(evidence["overall"]),
        "dimensions": evidence["dimension_averages"],
        "perTopic": evidence["per_topic"],
        "coverage": {
            "questionsAsked": state.questions_asked,
            "daysCovered": state.covered_days(),
            "modules": sorted({t["module"] for t in evidence["per_topic"]}),
        },
        "headline": coerce_text(raw.get("headline_observation"), "", 400),
        "behaviours": evidence["behaviours"],
        "timeline": build_timeline(state),
        "claims": [
            {
                "text": c.text,
                "topic": c.topic,
                "status": c.status.value,
                "turn": c.turn_index,
                "evidence": c.evidence[:2],
            }
            for c in state.claims
        ],
        "missedObjectives": evidence["missing_points"][:8],
        "groundingWarnings": warnings,
        "generatedBy": routed.provider,
        "degraded": routed.degraded,
    }
    return feedback, report, routed.notes + warnings


# --------------------------------------------------------------------------
# Deterministic fallbacks — used when the model returns an unusable field.
# --------------------------------------------------------------------------
def _fallback_summary(evidence: dict[str, Any]) -> str:
    return (
        f"{evidence['name']} answered {evidence['questions']} questions across "
        f"{evidence['days']} curriculum days, scoring {evidence['overall']}/100 overall. "
        "See the per-topic breakdown for where the score came from."
    )


def _fallback_strengths(evidence: dict[str, Any]) -> list[str]:
    ranked = sorted(evidence["per_topic"], key=lambda t: t["score"], reverse=True)
    return [f"{t['topic']} (Day {t['day']}) — {t['score']}/100" for t in ranked[:2]] or [
        "Completed the interview"
    ]


def _fallback_gaps(evidence: dict[str, Any]) -> list[str]:
    ranked = sorted(evidence["per_topic"], key=lambda t: t["score"])
    return [f"{t['topic']} (Day {t['day']}) — {t['score']}/100" for t in ranked[:2]] or [
        "Not enough answers to identify a specific gap"
    ]


def _fallback_next(evidence: dict[str, Any]) -> list[str]:
    ranked = sorted(evidence["per_topic"], key=lambda t: t["score"])
    if not ranked:
        return ["Re-run the cohort exercises and record what you observe"]
    worst = ranked[0]
    return [
        f"Rebuild the Day {worst['day']} exercise ({worst['topic']}) and write down the numbers you see",
        "Practise explaining one project with concrete metrics instead of adjectives",
    ]
