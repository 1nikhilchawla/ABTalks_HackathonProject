"""Provider-agnostic LLM interface.

One method matters: ``structured`` — give it a JSON schema, get back a dict.
Free-form generation is expressed as a schema with a single string field, which
keeps every call site on the same validated path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(RuntimeError):
    """Base for anything that should trigger a retry or a provider fallback."""

    retryable = True


class LLMTimeout(LLMError):
    pass


class LLMRateLimited(LLMError):
    def __init__(self, message: str, retry_after: float = 2.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMBadResponse(LLMError):
    """Model replied, but not with usable structured data."""


class LLMAuthError(LLMError):
    retryable = False


@dataclass
class LLMResult:
    data: dict[str, Any]
    provider: str
    model: str
    latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    repaired: bool = False
    attempts: int = 1

    def cost_note(self) -> str:
        return f"{self.provider}/{self.model} {self.input_tokens}in/{self.output_tokens}out"


@dataclass
class UsageLedger:
    """Cheap running total so the UI can show real cost/latency, not vibes."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_latency_ms: int = 0
    failures: int = 0
    fallbacks: int = 0
    by_provider: dict[str, int] = field(default_factory=dict)

    def record(self, result: LLMResult) -> None:
        self.calls += 1
        self.input_tokens += result.input_tokens
        self.output_tokens += result.output_tokens
        self.total_latency_ms += result.latency_ms
        self.by_provider[result.provider] = self.by_provider.get(result.provider, 0) + 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "avgLatencyMs": int(self.total_latency_ms / self.calls) if self.calls else 0,
            "failures": self.failures,
            "fallbacks": self.fallbacks,
            "byProvider": dict(self.by_provider),
        }


class LLMProvider(Protocol):
    name: str
    model: str

    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        schema_name: str,
        max_tokens: int = 900,
        temperature: float = 0.4,
        # Structured context for providers that reason over data rather than
        # prose (the offline rubric engine). API providers ignore it.
        context: dict[str, Any] | None = None,
    ) -> LLMResult: ...

    async def aclose(self) -> None: ...


class CircuitBreaker:
    """Stop hammering a provider that is clearly down."""

    def __init__(self, threshold: int, cooldown: float) -> None:
        self.threshold = max(1, threshold)
        self.cooldown = cooldown
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self.cooldown:
            # Half-open: let one request through.
            self._opened_at = None
            self._failures = self.threshold - 1
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.threshold:
            self._opened_at = time.monotonic()

    def state(self) -> str:
        return "open" if self.is_open else ("degraded" if self._failures else "closed")
