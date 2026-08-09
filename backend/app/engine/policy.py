"""The interview policy — a deterministic decision function over state.

Why deterministic and not "let the model decide what to do next": an LLM that
picks its own control flow will occasionally loop, re-ask, or end an interview
after three questions. Here the *content* of every question is model-generated,
but the *control flow* is a state machine with hard guards. That combination is
what makes the interview both adaptive and provably terminating.

Every decision carries a ``reason_code`` which the UI surfaces verbatim, so the
adaptation is auditable rather than asserted.
"""

from __future__ import annotations

from ..config import InterviewLimits
from ..models.domain import (
    Action,
    AnswerEvaluation,
    Decision,
    InterviewState,
    SlotKind,
    Stage,
    TopicSlot,
    Utterance,
)

_STAGE_FOR_KIND = {
    SlotKind.WARMUP: Stage.WARMUP,
    SlotKind.CORE: Stage.CORE,
    SlotKind.PROBE: Stage.PROBE,
    SlotKind.GAP: Stage.GAP,
    SlotKind.SYNTHESIS: Stage.SYNTHESIS,
    SlotKind.BEHAVIORAL: Stage.WRAP,
}

_CHALLENGE_FLAGS = {"overclaiming", "no_concrete_metrics", "buzzword_heavy", "memorised_sounding"}


def next_open_slot(state: InterviewState) -> TopicSlot | None:
    for slot in state.plan:
        if not slot.closed and slot.questions_asked == 0:
            return slot
    for slot in state.plan:
        if not slot.closed:
            return slot
    return None


def coverage_satisfied(state: InterviewState, limits: InterviewLimits) -> bool:
    return (
        state.questions_asked >= limits.min_questions
        and len(state.covered_days()) >= limits.min_distinct_days
    )


def _remaining_capacity(state: InterviewState) -> int:
    """How many more questions the untouched plan could still supply."""
    return sum(1 for s in state.plan if not s.closed and s.questions_asked == 0)


def _must_deepen(state: InterviewState, limits: InterviewLimits) -> bool:
    """True when closing this topic would make the coverage floor unreachable."""
    projected = state.questions_asked + _remaining_capacity(state)
    return projected < limits.min_questions


def decide(
    state: InterviewState,
    limits: InterviewLimits,
    utterance: Utterance | None,
    evaluation: AnswerEvaluation | None,
    volunteered: TopicSlot | None = None,
) -> Decision:
    """Choose the next interviewer action. Pure function of the arguments.

    ``volunteered`` is a planned topic the candidate's own answer matched more
    strongly than the current one (see ``engine/topics.py``). Following it is
    what an attentive human interviewer does, so it outranks the generic
    adaptive branches below.
    """

    active = state.active_slot

    # ---- hard termination guards (checked before anything adaptive) -----
    if len(state.turns) >= limits.max_turns:
        return _end(state, "turn_budget_exhausted")
    if state.questions_asked >= limits.max_questions:
        return _end(state, "question_budget_reached")
    if utterance is Utterance.END_REQUEST and state.questions_asked >= 3:
        return _end(state, "candidate_requested_end")
    if utterance is Utterance.END_REQUEST:
        return _meta(state, Action.HANDLE_META, "early_end_request_declined")

    # ---- non-answers: handled without consuming the question budget -----
    if utterance is not None and utterance is not Utterance.ANSWER:
        # Process events are always serviced, even mid-disengagement: a
        # candidate who asks "can you repeat that?" must get the question back,
        # not get their topic taken away.
        if utterance is Utterance.REQUEST_REPEAT:
            return _meta(state, Action.HANDLE_META, "candidate_asked_for_repeat")
        if utterance is Utterance.META_QUESTION:
            return _meta(state, Action.HANDLE_META, "candidate_asked_interviewer_a_question")
        if utterance is Utterance.MANIPULATION:
            return _meta(state, Action.HANDLE_META, "prompt_injection_detected")
        if utterance is Utterance.REQUEST_HINT:
            return _meta(state, Action.GIVE_HINT, "candidate_requested_hint")

        # Genuine disengagement: bounded before we start burning the plan.
        if state.consecutive_non_answers >= limits.max_consecutive_non_answers:
            if coverage_satisfied(state, limits):
                return _end(state, "repeated_non_answers_after_coverage")
            return _new_topic(state, limits, "moving_on_after_repeated_non_answers", drop=1)

        if utterance is Utterance.EMPTY:
            return _meta(state, Action.CLARIFY, "empty_response")
        if utterance is Utterance.REFUSAL:
            if coverage_satisfied(state, limits):
                return _end(state, "candidate_refused_after_coverage")
            return _new_topic(state, limits, "candidate_refused_topic", drop=0)
        if utterance is Utterance.REQUEST_SKIP:
            return _new_topic(state, limits, "candidate_requested_skip", drop=0)
        if utterance is Utterance.DONT_KNOW:
            # One rescue attempt at lower difficulty, then move on.
            if active and active.followups_used < 1 and state.difficulty > 1:
                return Decision(
                    intent=Action.DECREASE_DIFFICULTY,
                    topic=active.day_title,
                    day=active.day,
                    slot_id=active.slot_id,
                    difficulty=max(1, state.difficulty - 1),
                    reason_code="dont_know_probe_fundamentals",
                    question_type="fundamentals",
                    confidence=0.8,
                    evidence=["candidate said they did not know"],
                )
            return _new_topic(state, limits, "dont_know_topic_exhausted", drop=1)

    # ---- opening move ---------------------------------------------------
    if active is None or evaluation is None:
        return _new_topic(state, limits, "opening_topic" if not state.questions_asked else "no_active_topic")

    # ---- coverage floor reached and plan finished -> wrap up ------------
    if coverage_satisfied(state, limits) and _remaining_capacity(state) == 0 and active.closed:
        return _end(state, "plan_complete_and_coverage_met")

    verdict = evaluation.verdict
    flags = set(evaluation.flags)
    can_follow_up = active.followups_used < limits.max_followups_per_topic

    # ---- follow the candidate ------------------------------------------
    # Their answer matched a different planned day far better than this one.
    # That is not drift, it is an opening — take it while it is live.
    #
    # The substance test lives in ``topics.detect_volunteered_topic`` (a BM25
    # floor against the target day), not here. Rubric dimensions are computed
    # against the *current* day, so an answer genuinely about another topic
    # scores low on all of them — gating on the verdict would make this branch
    # unreachable, which is exactly the bug this comment exists to prevent.
    if (
        volunteered is not None
        and evaluation.verdict != "non_answer"
        and active.questions_asked >= 1
    ):
        return Decision(
            intent=Action.ASK_NEW_TOPIC,
            topic=volunteered.day_title,
            day=volunteered.day,
            slot_id=volunteered.slot_id,
            difficulty=max(1, min(volunteered.base_difficulty, 5)),
            reason_code="candidate_volunteered_topic",
            question_type=_question_type_for(volunteered),
            confidence=0.75,
            evidence=[f"answer matched day {volunteered.day} ({volunteered.day_title})"],
        )

    # ---- adaptive branch ------------------------------------------------
    if verdict == "strong" and can_follow_up and state.difficulty < 5:
        return Decision(
            intent=Action.INCREASE_DIFFICULTY,
            topic=active.day_title,
            day=active.day,
            slot_id=active.slot_id,
            difficulty=min(5, state.difficulty + 1),
            reason_code="strong_answer_raise_difficulty",
            question_type="technical_depth",
            confidence=float(evaluation.confidence),
            evidence=[evaluation.evidence_quote or evaluation.followup_hook],
        )

    if flags & _CHALLENGE_FLAGS and can_follow_up and evaluation.followup_hook:
        return Decision(
            intent=Action.CHALLENGE_CLAIM,
            topic=active.day_title,
            day=active.day,
            slot_id=active.slot_id,
            difficulty=state.difficulty,
            reason_code="claim_requires_validation:" + ",".join(sorted(flags & _CHALLENGE_FLAGS)),
            question_type="claim_verification",
            confidence=float(evaluation.confidence),
            evidence=[evaluation.followup_hook],
        )

    if "possibly_off_topic" in flags and can_follow_up:
        return Decision(
            intent=Action.REDIRECT,
            topic=active.day_title,
            day=active.day,
            slot_id=active.slot_id,
            difficulty=state.difficulty,
            reason_code="answer_drifted_from_question",
            question_type="redirect",
            confidence=0.7,
            evidence=[evaluation.evidence_quote],
        )

    if verdict == "weak":
        if state.consecutive_weak >= 2 and not _must_deepen(state, limits):
            return _new_topic(state, limits, "two_weak_answers_change_topic", drop=1)
        if can_follow_up:
            return Decision(
                intent=Action.DECREASE_DIFFICULTY,
                topic=active.day_title,
                day=active.day,
                slot_id=active.slot_id,
                difficulty=max(1, state.difficulty - 1),
                reason_code="weak_answer_probe_fundamentals",
                question_type="fundamentals",
                confidence=float(evaluation.confidence),
                evidence=evaluation.missing_points[:1] or [evaluation.rationale],
            )
        return _new_topic(state, limits, "weak_answer_topic_exhausted", drop=1)

    if verdict == "non_answer":
        return _new_topic(state, limits, "non_answer_after_evaluation", drop=1)

    # adequate
    if can_follow_up and (evaluation.followup_hook or _must_deepen(state, limits)):
        return Decision(
            intent=Action.FOLLOW_UP,
            topic=active.day_title,
            day=active.day,
            slot_id=active.slot_id,
            difficulty=state.difficulty,
            reason_code=(
                "coverage_floor_requires_depth" if _must_deepen(state, limits)
                else "adequate_answer_probe_specifics"
            ),
            question_type="technical_depth",
            confidence=float(evaluation.confidence),
            evidence=[evaluation.followup_hook or "answer lacked specifics"],
        )

    return _new_topic(state, limits, "topic_covered_move_on")


# --------------------------------------------------------------------------
# builders
# --------------------------------------------------------------------------
def _end(state: InterviewState, reason: str) -> Decision:
    return Decision(
        intent=Action.END_INTERVIEW,
        topic="wrap-up",
        difficulty=state.difficulty,
        reason_code=reason,
        question_type="closing",
        confidence=0.95,
    )


def _meta(state: InterviewState, action: Action, reason: str) -> Decision:
    active = state.active_slot
    return Decision(
        intent=action,
        topic=active.day_title if active else "interview process",
        day=active.day if active else None,
        slot_id=active.slot_id if active else None,
        difficulty=state.difficulty,
        reason_code=reason,
        question_type="meta",
        confidence=0.9,
    )


def _new_topic(
    state: InterviewState, limits: InterviewLimits, reason: str, drop: int = 0
) -> Decision:
    slot = next_open_slot(state)
    if slot is None:
        if coverage_satisfied(state, limits):
            return _end(state, "no_topics_left_coverage_met")
        # Coverage not met but plan exhausted: deepen the last topic instead of
        # ending short of the brief's floor.
        active = state.active_slot or (state.plan[-1] if state.plan else None)
        if active is None:
            return _end(state, "no_plan_available")
        return Decision(
            intent=Action.FOLLOW_UP,
            topic=active.day_title,
            day=active.day,
            slot_id=active.slot_id,
            difficulty=state.difficulty,
            reason_code="coverage_floor_not_met_extending",
            question_type="technical_depth",
            confidence=0.6,
        )

    difficulty = max(1, min(slot.base_difficulty - drop, 5))
    return Decision(
        intent=Action.ASK_NEW_TOPIC,
        topic=slot.day_title,
        day=slot.day,
        slot_id=slot.slot_id,
        difficulty=difficulty,
        reason_code=reason,
        question_type=_question_type_for(slot),
        confidence=0.85,
        evidence=[f"day {slot.day}: {slot.signal}"],
    )


def _question_type_for(slot: TopicSlot) -> str:
    return {
        SlotKind.WARMUP: "calibration",
        SlotKind.CORE: "technical_depth",
        SlotKind.PROBE: "fundamentals",
        SlotKind.GAP: "gap_check",
        SlotKind.SYNTHESIS: "system_design",
        SlotKind.BEHAVIORAL: "behavioral",
    }[slot.kind]


def stage_for(slot: TopicSlot | None) -> Stage:
    if slot is None:
        return Stage.WRAP
    return _STAGE_FOR_KIND.get(slot.kind, Stage.CORE)
