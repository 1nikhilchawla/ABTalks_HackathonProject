"""The offline rubric engine must actually discriminate.

A dimension that returns the same band for every input is worse than no
dimension: it looks like a measurement and carries no information. The
`communication` axis previously did exactly that (84-100 for any answer over
twelve words), so these tests pin the property, not the formula.
"""

from __future__ import annotations

import asyncio

import pytest

from app.llm.heuristic_provider import HeuristicProvider

STRUCTURED = (
    "I built the retrieval layer on ChromaDB. First I chunked the plan documents at 800 tokens "
    "with 100 overlap, then I attached plan_type metadata so I could filter before the vector "
    "search. Recall at 5 went from 61% to 78% because the filter removed cross-plan noise."
)
VAGUE = "Yeah we basically leveraged best practices and it was pretty robust and scalable overall."
TERSE = "I used Chroma."
RUN_ON = (
    "So we had this whole system where the retrieval was happening and then the model would get "
    "the context and it would generate an answer and we also had some caching in there and the "
    "frontend would stream it and honestly there were a lot of moving parts that all had to work "
    "together for the thing to actually respond properly to a user question about their plan."
)


def score(answer: str, question: str = "How did you build the retrieval layer?", day: int = 10):
    provider = HeuristicProvider()
    result = asyncio.run(
        provider.structured(
            system="", user="", schema={}, schema_name="answer_evaluation",
            context={"answer": answer, "question": question, "day": day},
        )
    )
    return result.data["scores"]


def test_communication_discriminates_across_answer_shapes():
    values = [score(a)["communication"] for a in (STRUCTURED, VAGUE, TERSE, RUN_ON)]
    assert max(values) - min(values) >= 20, f"communication is not discriminating: {values}"
    assert max(values) < 90, "communication should not pin to the top of the scale"


def test_structured_answer_beats_vague_answer_on_communication():
    assert score(STRUCTURED)["communication"] > score(VAGUE)["communication"]


def test_run_on_is_penalised_but_not_annihilated():
    value = score(RUN_ON)["communication"]
    assert 10 <= value < score(STRUCTURED)["communication"]


def test_specificity_separates_metrics_from_adjectives():
    assert score(STRUCTURED)["specificity"] - score(VAGUE)["specificity"] > 40


@pytest.mark.parametrize("answer", [STRUCTURED, VAGUE, TERSE, RUN_ON])
def test_all_dimensions_stay_in_range(answer):
    assert all(0 <= v <= 100 for v in score(answer).values())


def test_engine_is_deterministic():
    assert score(STRUCTURED) == score(STRUCTURED)


def test_no_single_dimension_is_constant_across_the_corpus():
    """Catches the class of bug this file exists for, for every dimension."""
    corpus = [STRUCTURED, VAGUE, TERSE, RUN_ON]
    by_dimension: dict[str, set[int]] = {}
    for answer in corpus:
        for dimension, value in score(answer).items():
            by_dimension.setdefault(dimension, set()).add(value)
    constant = [d for d, values in by_dimension.items() if len(values) == 1]
    assert not constant, f"dimensions carry no information: {constant}"
