"""Provider router: retries, backoff, circuit breaking, and a guaranteed floor.

Call sites never handle an LLM exception. They ask for structured data and
always receive it, plus a ``degraded`` flag describing how hard the system had
to work to get it. That single guarantee removes most of the failure surface
from the engine.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Any

from ..config import Settings, get_settings
from .anthropic_provider import AnthropicProvider
from .base import (
    CircuitBreaker,
    LLMAuthError,
    LLMError,
    LLMProvider,
    LLMRateLimited,
    LLMResult,
    UsageLedger,
)
from .heuristic_provider import HeuristicProvider
from .openai_provider import OpenAICompatibleProvider

log = logging.getLogger("cohortiq.llm")


@dataclass
class RoutedResult:
    result: LLMResult
    degraded: bool
    notes: list[str]

    @property
    def data(self) -> dict[str, Any]:
        return self.result.data

    @property
    def provider(self) -> str:
        return self.result.provider


class LLMRouter:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.usage = UsageLedger()
        self._providers: dict[str, LLMProvider] = {}
        self._breakers: dict[str, CircuitBreaker] = {}
        self._chain = self.settings.resolved_provider_chain()

    # ---- construction --------------------------------------------------
    def _provider(self, name: str) -> LLMProvider | None:
        if name in self._providers:
            return self._providers[name]
        s = self.settings
        provider: LLMProvider | None = None
        try:
            if name == "anthropic" and s.anthropic_api_key:
                provider = AnthropicProvider(
                    s.anthropic_api_key, s.anthropic_model, s.anthropic_base_url, s.llm_timeout_seconds
                )
            elif name == "openai" and s.openai_api_key:
                provider = OpenAICompatibleProvider(
                    name="openai", api_key=s.openai_api_key, model=s.openai_model,
                    base_url=s.openai_base_url, timeout=s.llm_timeout_seconds,
                )
            elif name == "groq" and s.groq_api_key:
                provider = OpenAICompatibleProvider(
                    name="groq", api_key=s.groq_api_key, model=s.groq_model,
                    base_url=s.groq_base_url, timeout=s.llm_timeout_seconds,
                    supports_json_schema=False,
                )
            elif name == "heuristic":
                provider = HeuristicProvider()
        except Exception as exc:  # pragma: no cover - construction is trivial
            log.warning("provider %s failed to construct: %s", name, exc)
            provider = None
        if provider is not None:
            self._providers[name] = provider
            self._breakers[name] = CircuitBreaker(
                self.settings.llm_breaker_threshold, self.settings.llm_breaker_cooldown
            )
        return provider

    @property
    def primary_name(self) -> str:
        return self._chain[0] if self._chain else "heuristic"

    def is_live(self) -> bool:
        """True when a real model provider is configured."""
        return self.primary_name != "heuristic"

    def health(self) -> dict[str, Any]:
        return {
            "chain": self._chain,
            "primary": self.primary_name,
            "live": self.is_live(),
            "breakers": {k: v.state() for k, v in self._breakers.items()},
            "usage": self.usage.snapshot(),
        }

    # ---- the one public call ------------------------------------------
    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        schema_name: str,
        context: dict[str, Any] | None = None,
        max_tokens: int = 900,
        temperature: float = 0.4,
    ) -> RoutedResult:
        notes: list[str] = []
        degraded = False

        for position, name in enumerate(self._chain):
            provider = self._provider(name)
            if provider is None:
                continue
            breaker = self._breakers[name]
            if breaker.is_open:
                notes.append(f"{name}: circuit open, skipped")
                degraded = True
                continue

            attempts = 1 if name == "heuristic" else self.settings.llm_max_retries + 1
            for attempt in range(1, attempts + 1):
                try:
                    result = await provider.structured(
                        system=system, user=user, schema=schema, schema_name=schema_name,
                        max_tokens=max_tokens, temperature=temperature, context=context,
                    )
                    result.attempts = attempt
                    breaker.record_success()
                    self.usage.record(result)
                    if position > 0:
                        self.usage.fallbacks += 1
                        degraded = True
                        notes.append(f"fell back to {name}")
                    if result.repaired:
                        notes.append(f"{name}: JSON repaired")
                    return RoutedResult(result=result, degraded=degraded, notes=notes)

                except LLMAuthError as exc:
                    self.usage.failures += 1
                    breaker.record_failure()
                    notes.append(f"{name}: {exc}")
                    degraded = True
                    break  # a bad key will not fix itself on retry
                except LLMRateLimited as exc:
                    self.usage.failures += 1
                    notes.append(f"{name}: rate limited (attempt {attempt})")
                    degraded = True
                    if attempt < attempts:
                        await asyncio.sleep(min(exc.retry_after, 6.0))
                        continue
                    breaker.record_failure()
                except LLMError as exc:
                    self.usage.failures += 1
                    notes.append(f"{name}: {type(exc).__name__} (attempt {attempt})")
                    degraded = True
                    if attempt < attempts and getattr(exc, "retryable", True):
                        await asyncio.sleep(_backoff(attempt))
                        continue
                    breaker.record_failure()
                except Exception as exc:  # never let a provider bug escape
                    self.usage.failures += 1
                    breaker.record_failure()
                    notes.append(f"{name}: unexpected {type(exc).__name__}")
                    log.exception("unexpected provider error in %s", name)
                    degraded = True
                    break

        # The heuristic provider cannot fail, but be defensive anyway.
        fallback = HeuristicProvider()
        result = await fallback.structured(
            system=system, user=user, schema=schema, schema_name=schema_name, context=context
        )
        notes.append("all providers exhausted; offline rubric engine used")
        return RoutedResult(result=result, degraded=True, notes=notes)

    async def aclose(self) -> None:
        for provider in self._providers.values():
            try:
                await provider.aclose()
            except Exception:  # pragma: no cover
                pass


def _backoff(attempt: int) -> float:
    return min(0.5 * (2 ** (attempt - 1)) + random.uniform(0, 0.25), 4.0)
