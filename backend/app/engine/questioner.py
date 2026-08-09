"""Question generation with a repetition guard.

The policy decides *what move* to make; this module renders that move into
something a human would say. Two things happen after generation: the text is
cleaned of the artefacts models produce when told to "speak" (markdown, double
questions, meta-commentary), and it is checked for near-duplication against
everything already asked. A repeated question is the single most immersion-
breaking failure in an interview product, so it is caught mechanically.
"""

from __future__ import annotations

import re

from ..llm.json_repair import coerce_text
from ..llm.router import LLMRouter
from ..llm.schemas import INTERVIEW_QUESTION_SCHEMA
from ..models.domain import Action, Decision, InterviewState
from . import prompts
from .topics import target_objective

_MARKDOWN = re.compile(r"^[\s>*\-•#]+|\*\*|__|`", re.M)
_LEADING_LABEL = re.compile(r"^(question|q\d*|interviewer)\s*[:.\-]\s*", re.I)
_MULTI_QUESTION = re.compile(r"\?[^?]*\?")


async def generate_question(
    *,
    router: LLMRouter,
    state: InterviewState,
    decision: Decision,
    hook: str = "",
) -> tuple[str, str, list[str]]:
    """Return (spoken_text, internal_note, router_notes)."""
    # Retrieval picks the objective this candidate has covered least, so a
    # second question on a topic breaks new ground instead of rephrasing.
    focus = target_objective(state, decision.day) if decision.day else None

    routed = await router.structured(
        system=prompts.question_system(state.persona),
        user=prompts.question_user(state, decision, hook=hook, focus_objective=focus or ""),
        schema=INTERVIEW_QUESTION_SCHEMA,
        schema_name="interview_question",
        context={
            "action": decision.intent.value,
            "day": decision.day,
            "hook": hook or decision.evidence[0] if decision.evidence else hook,
            "objective": focus,
            "session_id": state.session_id,
            "turn": len(state.turns),
        },
        max_tokens=400,
        temperature=0.65,
    )

    question = _clean(coerce_text(routed.data.get("question"), "", 900))
    ack = _clean(coerce_text(routed.data.get("acknowledgement"), "", 200))
    note = coerce_text(routed.data.get("internal_note"), "", 300)
    notes = list(routed.notes)

    if not question:
        question = _fallback_text(state, decision)
        notes.append("empty question from provider; template used")

    if _is_repeat(state, question):
        notes.append("duplicate question detected; regenerating once")
        retry = await router.structured(
            system=prompts.question_system(state.persona),
            user=prompts.question_user(
                state, decision, hook=hook, focus_objective=focus or ""
            )
            + "\n\nIMPORTANT: your previous attempt repeated an earlier question. Ask about a "
            "different aspect of this topic.",
            schema=INTERVIEW_QUESTION_SCHEMA,
            schema_name="interview_question",
            context={
                "action": decision.intent.value,
                "day": decision.day,
                "hook": hook,
                "objective": focus,
                "session_id": state.session_id,
                "turn": len(state.turns) + 1,
            },
            max_tokens=400,
            temperature=0.9,
        )
        candidate = _clean(coerce_text(retry.data.get("question"), "", 900))
        notes.extend(retry.notes)
        if candidate and not _is_repeat(state, candidate):
            question = candidate
        else:
            question = _fallback_text(state, decision)
            notes.append("regeneration still duplicate; template used")

    spoken = f"{ack} {question}".strip() if ack and decision.intent is not Action.ASK_NEW_TOPIC else question
    return spoken, note, notes


def _clean(text: str) -> str:
    if not text:
        return ""
    out = _MARKDOWN.sub("", text).strip()
    out = _LEADING_LABEL.sub("", out).strip()
    out = re.sub(r"\s+", " ", out)
    # Collapse stacked questions to the first one — one question per turn.
    match = _MULTI_QUESTION.search(out)
    if match and len(out) > 140:
        first_end = out.find("?") + 1
        if first_end > 40:
            out = out[:first_end]
    return out.strip()


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower())


def _is_repeat(state: InterviewState, question: str) -> bool:
    new_tokens = set(_normalise(question).split())
    if len(new_tokens) < 4:
        return False
    for turn in state.turns:
        if turn.role != "interviewer":
            continue
        old_tokens = set(_normalise(turn.text).split())
        if not old_tokens:
            continue
        overlap = len(new_tokens & old_tokens) / max(len(new_tokens | old_tokens), 1)
        if overlap >= 0.7:
            return True
    return False


def _fallback_text(state: InterviewState, decision: Decision) -> str:
    """Deterministic phrasing when generation fails outright."""
    slot = state.slot(decision.slot_id)
    title = slot.day_title if slot else decision.topic
    objective = slot.objectives[0] if slot and slot.objectives else "the work you did there"
    obj = objective[0].lower() + objective[1:] if objective else objective

    if decision.intent is Action.ASK_NEW_TOPIC:
        return f"Let's talk about {title}. Walk me through how you approached {obj}."
    if decision.intent is Action.DECREASE_DIFFICULTY:
        return f"Let's take a step back on {title}. In your own words, what problem does it solve?"
    if decision.intent is Action.INCREASE_DIFFICULTY:
        return f"Harder version: in {title}, what breaks first at scale, and how would you detect it?"
    if decision.intent is Action.CHALLENGE_CLAIM:
        return "How did you verify that, rather than assuming it worked?"
    if decision.intent is Action.REDIRECT:
        return f"That went somewhere else. Back to {title} — what did you actually implement?"
    if decision.intent is Action.CLARIFY:
        return "I didn't get anything usable there. Take another run at it, in a couple of sentences."
    if decision.intent is Action.GIVE_HINT:
        tool = slot.tools[0] if slot and slot.tools else "the tooling from that day"
        return f"Hint: think about {tool}. With that in mind, how would you approach it?"
    return f"Tell me more about {title} — specifically, what you personally built."
