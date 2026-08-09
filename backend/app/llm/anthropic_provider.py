"""Anthropic Messages API provider.

Structured output is obtained by forcing a single tool call whose input schema
is the schema we want. That is the most reliable structured-output path on this
API and it fails loudly rather than returning prose.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from .base import (
    LLMAuthError,
    LLMBadResponse,
    LLMError,
    LLMRateLimited,
    LLMResult,
    LLMTimeout,
)
from .json_repair import extract_json

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, base_url: str, timeout: float) -> None:
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout, connect=10.0),
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
        )

    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        schema_name: str,
        max_tokens: int = 900,
        temperature: float = 0.4,
        context: dict[str, Any] | None = None,  # unused; see HeuristicProvider
    ) -> LLMResult:
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [
                {
                    "name": schema_name,
                    "description": f"Emit the {schema_name} record. This is the only allowed output.",
                    "input_schema": schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": schema_name},
        }

        started = time.perf_counter()
        try:
            resp = await self._client.post("/v1/messages", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMTimeout(f"anthropic timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"anthropic transport error: {exc}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)

        if resp.status_code in (401, 403):
            raise LLMAuthError(f"anthropic auth failed ({resp.status_code})")
        if resp.status_code == 429:
            raise LLMRateLimited(
                "anthropic rate limited", retry_after=float(resp.headers.get("retry-after", 2))
            )
        if resp.status_code >= 500:
            raise LLMError(f"anthropic server error {resp.status_code}")
        if resp.status_code >= 400:
            raise LLMBadResponse(f"anthropic rejected request {resp.status_code}: {resp.text[:200]}")

        body = resp.json()
        usage = body.get("usage") or {}
        data: dict[str, Any] | None = None
        repaired = False

        for block in body.get("content") or []:
            if block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                data = block["input"]
                break
        if data is None:
            text = "".join(
                b.get("text", "") for b in (body.get("content") or []) if b.get("type") == "text"
            )
            data = extract_json(text)
            repaired = data is not None
        if data is None:
            raise LLMBadResponse("anthropic returned no structured content")

        return LLMResult(
            data=data,
            provider=self.name,
            model=self.model,
            latency_ms=latency_ms,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            repaired=repaired,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
