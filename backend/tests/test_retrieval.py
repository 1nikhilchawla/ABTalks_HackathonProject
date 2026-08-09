"""Retrieval must be load-bearing, not decorative.

These tests exist because it is easy to ship a search index that nothing calls.
They assert the two places BM25 actually changes the interview: which objective
gets asked about next, and whether the interviewer follows a candidate who
answers about a different curriculum day.
"""

from __future__ import annotations

from app.data.candidates import demo_candidates, parse_candidate
from app.data.curriculum import get_curriculum
from app.engine import policy, topics
from app.engine.planner import build_plan
from app.models.domain import (
    Action,
    AnswerEvaluation,
    DimensionScores,
    InterviewState,
    Turn,
    Utterance,
)


def make_state(limits, active_day: int | None = None) -> InterviewState:
    candidate = parse_candidate(demo_candidates()[0])
    state = InterviewState(session_id="r", candidate=candidate)
    state.plan = build_plan(candidate, limits)
    slot = next((s for s in state.plan if s.day == active_day), state.plan[0])
    state.active_slot_id = slot.slot_id
    slot.questions_asked = 1
    state.questions_asked = 1
    return state


def answer(state: InterviewState, text: str, day: int | None = None) -> None:
    state.add_turn(
        Turn(index=0, role="candidate", text=text, day=day or (state.active_slot.day if state.active_slot else None),
             slot_id=state.active_slot_id, utterance=Utterance.ANSWER)
    )


def evaluation(verdict="adequate", score=60) -> AnswerEvaluation:
    return AnswerEvaluation(
        scores=DimensionScores(**{k: score for k in DimensionScores().model_dump()}),
        verdict=verdict,
        followup_hook="the retriever",
        rationale="test",
    )


# --------------------------------------------------------------------------
# Objective ranking
# --------------------------------------------------------------------------
def test_rank_objectives_puts_uncovered_first():
    curriculum = get_curriculum()
    day = 7  # Embeddings Explained
    covered = (
        "I generated embeddings for every knowledge base chunk with sentence transformers "
        "and stored them next to the original documents."
    )
    ranked = curriculum.rank_objectives(day, covered)
    assert len(ranked) == len(curriculum.day(day).objectives)

    least, most = ranked[0][0], ranked[-1][0]
    assert least != most
    # The objective the text explicitly describes must not be ranked as unexplored.
    assert "embeddings for every knowledge base chunk" not in least.lower()
    assert ranked[0][1] <= ranked[-1][1]


def test_least_covered_objective_moves_as_the_candidate_talks(limits):
    curriculum = get_curriculum()
    state = make_state(limits, active_day=7)
    first = topics.target_objective(state, 7)

    answer(state, first or "", day=7)
    second = topics.target_objective(state, 7)

    assert first is not None and second is not None
    assert first != second, "answering an objective should move the target off it"


def test_target_objective_is_deterministic(limits):
    state = make_state(limits, active_day=7)
    assert topics.target_objective(state, 7) == topics.target_objective(state, 7)


# --------------------------------------------------------------------------
# Volunteered-topic detection
# --------------------------------------------------------------------------
def test_answer_about_another_planned_day_is_detected(limits):
    state = make_state(limits, active_day=7)  # active topic: embeddings
    mcp_answer = (
        "I built an MCP server with the Model Context Protocol Python SDK and exposed three tools "
        "to Claude Desktop over stdio, then verified tool execution through live MCP calls."
    )
    volunteered = topics.detect_volunteered_topic(state, mcp_answer)

    planned_days = {s.day for s in state.plan}
    if 23 in planned_days:
        assert volunteered is not None
        assert volunteered.day.day == 23
        assert volunteered.margin > 1.0


def test_on_topic_answer_does_not_trigger_a_jump(limits):
    state = make_state(limits, active_day=7)
    on_topic = (
        "I generated embeddings for every knowledge base chunk, stored them with the source "
        "documents, and visualised the clusters with PCA to check that similar concepts grouped."
    )
    assert topics.detect_volunteered_topic(state, on_topic) is None


def test_short_answers_never_trigger_a_jump(limits):
    state = make_state(limits, active_day=7)
    assert topics.detect_volunteered_topic(state, "I used MCP.") is None


def test_no_jump_when_the_real_match_is_not_on_the_plan(limits):
    """The bug this guard exists for.

    An answer entirely about MCP, on a plan that contains no MCP day, must not
    be redirected to whichever planned day happens to share a few incidental
    terms. Searching only planned slots produced exactly that: the interviewer
    announced "let's move to the capstone" about an answer that was not about
    the capstone.
    """
    state = make_state(limits, active_day=7)
    # Remove any genuine MCP day so the global best match is unplanned.
    state.plan = [s for s in state.plan if s.day != 23]
    if state.active_slot is None:
        state.active_slot_id = state.plan[0].slot_id

    mcp_answer = (
        "I built an MCP server with the Model Context Protocol Python SDK and exposed three tools "
        "to Claude Desktop over stdio, then verified tool execution through live MCP interactions."
    )
    volunteered = topics.detect_volunteered_topic(state, mcp_answer)
    if volunteered is not None:
        # Only acceptable outcome: the day we jumped to really is the global
        # best match for that answer.
        assert get_curriculum().best_day_for(mcp_answer).day == volunteered.day.day


def test_jumps_are_budgeted(limits):
    """Following the candidate is a moment, not a mode."""
    state = make_state(limits, active_day=7)
    state.volunteered_jumps = topics.MAX_JUMPS_PER_INTERVIEW
    capstone_answer = (
        "I demonstrated the complete enterprise healthcare chatbot for the capstone, showcasing "
        "retrieval, RAG, agents, MCP and conversation memory with the production architecture."
    )
    assert topics.detect_volunteered_topic(state, capstone_answer) is None


def test_already_asked_topics_are_not_re_volunteered(limits):
    state = make_state(limits, active_day=7)
    for slot in state.plan:
        slot.questions_asked = max(slot.questions_asked, 1)
    mcp_answer = (
        "I built an MCP server exposing healthcare chatbot tools and connected it to an "
        "MCP-compatible client, verifying tool execution live."
    )
    assert topics.detect_volunteered_topic(state, mcp_answer) is None


# --------------------------------------------------------------------------
# The policy actually acts on it
# --------------------------------------------------------------------------
def test_policy_follows_a_volunteered_topic(limits):
    state = make_state(limits, active_day=7)
    target = next(s for s in state.plan if s.questions_asked == 0)

    decision = policy.decide(
        state, limits, Utterance.ANSWER, evaluation("adequate"), volunteered=target
    )
    assert decision.intent is Action.ASK_NEW_TOPIC
    assert decision.slot_id == target.slot_id
    assert decision.reason_code == "candidate_volunteered_topic"


def test_rambling_without_domain_content_is_not_a_volunteered_topic(limits):
    """The anti-evasion guard: dodging must not look like changing the subject.

    Waffle cannot clear the BM25 floor for a specific day, because that needs
    the day's actual technical vocabulary.
    """
    state = make_state(limits, active_day=7)
    waffle = (
        "Honestly there were a lot of moving parts and we basically did what made sense at the "
        "time, it was a team effort and things generally worked out pretty well in the end for us."
    )
    assert topics.detect_volunteered_topic(state, waffle) is None


def test_substantive_off_topic_answer_still_gets_followed(limits):
    """The gate is substance, not verdict.

    An answer genuinely about another day always scores badly against the
    current one, so gating on the verdict would make the branch unreachable.
    """
    state = make_state(limits, active_day=7)
    target = next(s for s in state.plan if s.questions_asked == 0)

    off_topic_but_solid = AnswerEvaluation(
        scores=DimensionScores(
            technical_accuracy=38, conceptual_depth=30, specificity=33,
            communication=64, practical_evidence=40, relevance=12,
        ),
        verdict="weak",  # every dimension is scored against the wrong topic
        followup_hook="the MCP server",
        rationale="test",
    )
    decision = policy.decide(
        state, limits, Utterance.ANSWER, off_topic_but_solid, volunteered=target
    )
    assert decision.reason_code == "candidate_volunteered_topic"
    assert decision.slot_id == target.slot_id


def test_non_answers_never_change_the_subject(limits):
    state = make_state(limits, active_day=7)
    target = next(s for s in state.plan if s.questions_asked == 0)
    decision = policy.decide(
        state, limits, Utterance.ANSWER, evaluation("non_answer", score=0), volunteered=target
    )
    assert decision.reason_code != "candidate_volunteered_topic"
