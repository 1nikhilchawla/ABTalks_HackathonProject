"""Provider failures must degrade, never crash."""

from __future__ import annotations

import asyncio

import pytest

from app.config import Settings
from app.engine.evaluator import _normalise
from app.llm.base import LLMError, LLMResult, LLMTimeout
from app.llm.router import LLMRouter
from app.llm.schemas import ANSWER_EVALUATION_SCHEMA


class ExplodingProvider:
    name = "exploding"
    model = "boom"

    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    async def structured(self, **kwargs):
        self.calls += 1
        raise self.exc

    async def aclose(self):
        return None


class FlakyProvider:
    """Fails once, then succeeds — the retry path."""

    name = "flaky"
    model = "flaky-1"

    def __init__(self):
        self.calls = 0

    async def structured(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise LLMTimeout("first call times out")
        return LLMResult(data={"question": "ok"}, provider=self.name, model=self.model, latency_ms=5)

    async def aclose(self):
        return None


def route(router, **kwargs):
    return asyncio.run(
        router.structured(
            system="s", user="u", schema=ANSWER_EVALUATION_SCHEMA,
            schema_name="answer_evaluation", **kwargs,
        )
    )


def make_router(provider) -> LLMRouter:
    router = LLMRouter(Settings(llm_provider="heuristic", llm_max_retries=2))
    router._chain = [provider.name, "heuristic"]
    router._providers[provider.name] = provider
    from app.llm.base import CircuitBreaker

    router._breakers[provider.name] = CircuitBreaker(3, 30.0)
    return router


def test_timeout_falls_back_to_offline_engine():
    provider = ExplodingProvider(LLMTimeout("timeout"))
    router = make_router(provider)
    result = route(router, context={"answer": "I used Chroma with metadata filters", "day": 8})
    assert result.degraded
    assert result.provider == "heuristic"
    assert "scores" in result.data


def test_retries_before_falling_back():
    provider = FlakyProvider()
    router = make_router(provider)
    result = route(router, context={"answer": "hello", "day": 7})
    assert provider.calls == 2
    assert result.provider == "flaky"


def test_circuit_breaker_opens_and_stops_calling():
    provider = ExplodingProvider(LLMError("server error"))
    router = make_router(provider)
    for _ in range(3):
        route(router, context={"answer": "x", "day": 7})
    calls_before = provider.calls
    route(router, context={"answer": "x", "day": 7})
    assert provider.calls == calls_before, "breaker should stop further calls"


def test_unexpected_exception_is_contained():
    provider = ExplodingProvider(ValueError("something unrelated blew up"))
    router = make_router(provider)
    result = route(router, context={"answer": "x", "day": 7})
    assert result.provider == "heuristic"


# --------------------------------------------------------------------------
# Evaluation normalisation against hostile model output
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"scores": "not-an-object", "verdict": "amazing"},
        {"scores": {"technical_accuracy": 900, "conceptual_depth": -40}, "flags": ["invented_flag"]},
        {"verdict": "non_answer", "scores": {k: 95 for k in
            ("technical_accuracy", "conceptual_depth", "specificity", "communication",
             "practical_evidence", "relevance")}},
        {"confidence": "very high", "missing_points": {"a": 1}, "claims": "one claim"},
    ],
)
def test_evaluator_normalises_garbage(payload):
    evaluation = _normalise(payload, answer="I built the retriever.", source="test")
    assert 0 <= evaluation.composite <= 100
    assert evaluation.verdict in {"strong", "adequate", "weak", "non_answer"}
    assert all(0 <= v <= 100 for v in evaluation.scores.as_dict().values())
    assert all(isinstance(f, str) for f in evaluation.flags)


def test_evaluator_drops_a_fabricated_quote():
    evaluation = _normalise(
        {"evidence_quote": "I deployed it on Kubernetes with Istio", "verdict": "strong"},
        answer="I used Chroma locally.",
        source="test",
    )
    assert evaluation.evidence_quote == ""


def test_non_answer_verdict_forces_low_scores():
    evaluation = _normalise(
        {"verdict": "non_answer", "scores": {k: 95 for k in
            ("technical_accuracy", "conceptual_depth", "specificity", "communication",
             "practical_evidence", "relevance")}},
        answer="uh",
        source="test",
    )
    assert evaluation.composite < 25
