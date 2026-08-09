"""State-machine guarantees: it adapts, and it always terminates."""

from __future__ import annotations

import pytest

from app.config import InterviewLimits
from app.data.candidates import demo_candidates, parse_candidate
from app.engine import policy
from app.engine.planner import build_plan
from app.models.domain import (
    Action,
    AnswerEvaluation,
    DimensionScores,
    InterviewState,
    Utterance,
)


def make_state(limits: InterviewLimits) -> InterviewState:
    candidate = parse_candidate(demo_candidates()[0])
    state = InterviewState(session_id="t", candidate=candidate)
    state.plan = build_plan(candidate, limits)
    state.active_slot_id = state.plan[0].slot_id
    state.plan[0].questions_asked = 1
    state.questions_asked = 1
    return state


def evaluation(verdict="adequate", *, flags=None, hook="the retriever", score=60):
    return AnswerEvaluation(
        scores=DimensionScores(**{k: score for k in DimensionScores().model_dump()}),
        verdict=verdict,
        flags=flags or [],
        followup_hook=hook,
        rationale="test",
    )


def test_strong_answer_raises_difficulty(limits):
    state = make_state(limits)
    state.difficulty = 3
    decision = policy.decide(state, limits, Utterance.ANSWER, evaluation("strong", score=85))
    assert decision.intent is Action.INCREASE_DIFFICULTY
    assert decision.difficulty == 4


def test_weak_answer_drops_to_fundamentals(limits):
    state = make_state(limits)
    state.difficulty = 4
    decision = policy.decide(state, limits, Utterance.ANSWER, evaluation("weak", score=30))
    assert decision.intent is Action.DECREASE_DIFFICULTY
    assert decision.difficulty == 3


def test_unsupported_claim_is_challenged(limits):
    state = make_state(limits)
    decision = policy.decide(
        state, limits, Utterance.ANSWER, evaluation(flags=["no_concrete_metrics"])
    )
    assert decision.intent is Action.CHALLENGE_CLAIM
    assert "claim_requires_validation" in decision.reason_code


def test_followups_are_capped_per_topic(limits):
    state = make_state(limits)
    state.plan[0].followups_used = limits.max_followups_per_topic
    decision = policy.decide(state, limits, Utterance.ANSWER, evaluation("strong", score=90))
    assert decision.intent is Action.ASK_NEW_TOPIC


def test_two_weak_answers_change_topic(limits):
    state = make_state(limits)
    state.consecutive_weak = 2
    state.questions_asked = 6
    for slot in state.plan[1:]:
        slot.closed = False
    decision = policy.decide(state, limits, Utterance.ANSWER, evaluation("weak", score=20))
    assert decision.intent is Action.ASK_NEW_TOPIC


def test_repeat_request_is_serviced_even_when_disengaged(limits):
    state = make_state(limits)
    state.consecutive_non_answers = 99
    decision = policy.decide(state, limits, Utterance.REQUEST_REPEAT, None)
    assert decision.reason_code == "candidate_asked_for_repeat"


def test_injection_never_ends_or_scores(limits):
    state = make_state(limits)
    decision = policy.decide(state, limits, Utterance.MANIPULATION, None)
    assert decision.intent is Action.HANDLE_META
    assert decision.reason_code == "prompt_injection_detected"


def test_early_end_request_is_declined(limits):
    state = make_state(limits)
    state.questions_asked = 2
    decision = policy.decide(state, limits, Utterance.END_REQUEST, None)
    assert decision.intent is not Action.END_INTERVIEW


def test_late_end_request_is_honoured(limits):
    state = make_state(limits)
    state.questions_asked = 9
    decision = policy.decide(state, limits, Utterance.END_REQUEST, None)
    assert decision.intent is Action.END_INTERVIEW


def test_question_budget_terminates(limits):
    state = make_state(limits)
    state.questions_asked = limits.max_questions
    assert policy.decide(state, limits, Utterance.ANSWER, evaluation()).intent is Action.END_INTERVIEW


def test_turn_budget_terminates(limits):
    from app.models.domain import Turn

    state = make_state(limits)
    for _ in range(limits.max_turns):
        state.add_turn(Turn(index=0, role="candidate", text="x"))
    assert policy.decide(state, limits, Utterance.ANSWER, evaluation()).intent is Action.END_INTERVIEW


def test_policy_cannot_loop_forever(limits):
    """Drive the machine with the worst possible input; it must still stop."""
    state = make_state(limits)
    from app.models.domain import Turn

    for _ in range(limits.max_turns + 5):
        decision = policy.decide(state, limits, Utterance.DONT_KNOW, None)
        if decision.intent is Action.END_INTERVIEW:
            return
        state.consecutive_non_answers += 1
        state.add_turn(Turn(index=0, role="candidate", text="i don't know"))
        slot = state.slot(decision.slot_id)
        if slot:
            slot.questions_asked += 1
            slot.followups_used += 1
            state.active_slot_id = slot.slot_id
            if decision.intent is Action.ASK_NEW_TOPIC:
                for other in state.plan:
                    if other.slot_id != slot.slot_id and other.questions_asked:
                        other.closed = True
        state.questions_asked += 1
    pytest.fail("policy never reached END_INTERVIEW")


def test_coverage_floor_forces_depth_when_plan_is_short(limits):
    state = make_state(limits)
    for slot in state.plan[1:]:
        slot.closed = True
    state.questions_asked = 3
    decision = policy.decide(state, limits, Utterance.ANSWER, evaluation())
    assert decision.intent is not Action.END_INTERVIEW
