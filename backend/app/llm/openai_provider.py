"""OpenAI-compatible provider — covers OpenAI, Groq, Together, vLLM and Ollama.

Tries strict ``json_schema`` response format first and falls back to
``json_object`` for gateways that do not implement it, so one class serves the
whole OpenAI-compatible ecosystem.
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


def _strictify(schema: dict[str, Any]) -> dict[str, Any]:
    """OpenAI strict mode requires every property to be listed as required."""
    node = dict(schema)
    if node.get("type") == "object":
        props = node.get("properties") or {}
        node["properties"] = {k: _strictify(v) for k, v in props.items()}
        node["required"] = list(props.keys())
        node["additionalProperties"] = False
    elif node.get("type") == "array" and isinstance(node.get("items"), dict):
        node["items"] = _strictify(node["items"])
    return node


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        model: str,
        base_url: str,
        timeout: float,
        supports_json_schema: bool = True,
    ) -> None:
        self.name = name
        self.model = model
        self._supports_json_schema = supports_json_schema
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout, connect=10.0),
            headers=headers,
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
        base_payload: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

        formats: list[dict[str, Any]] = []
        if self._supports_json_schema:
            formats.append(
                {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "strict": True,
                        "schema": _strictify(schema),
                    },
                }
            )
        formats.append({"type": "json_object"})

        last_error: Exception | None = None
        for response_format in formats:
            payload = dict(base_payload, response_format=response_format)
            started = time.perf_counter()
            try:
                resp = await self._client.post("/chat/completions", json=payload)
            except httpx.TimeoutException as exc:
                raise LLMTimeout(f"{self.name} timeout: {exc}") from exc
            except httpx.HTTPError as exc:
                raise LLMError(f"{self.name} transport error: {exc}") from exc

            latency_ms = int((time.perf_counter() - started) * 1000)

            if resp.status_code in (401, 403):
                raise LLMAuthError(f"{self.name} auth failed ({resp.status_code})")
            if resp.status_code == 429:
                raise LLMRateLimited(
                    f"{self.name} rate limited",
                    retry_after=float(resp.headers.get("retry-after", 2)),
                )
            if resp.status_code >= 500:
                raise LLMError(f"{self.name} server error {resp.status_code}")
            if resp.status_code >= 400:
                # Most likely: this gateway rejects json_schema. Try the next format.
                last_error = LLMBadResponse(
                    f"{self.name} rejected request {resp.status_code}: {resp.text[:200]}"
                )
                self._supports_json_schema = False
                continue

            body = resp.json()
            usage = body.get("usage") or {}
            choices = body.get("choices") or []
            content = ""
            if choices:
                content = (choices[0].get("message") or {}).get("content") or ""

            data = extract_json(content)
            if data is None:
                last_error = LLMBadResponse(f"{self.name} returned unparseable content")
                continue

            return LLMResult(
                data=data,
                provider=self.name,
                model=self.model,
                latency_ms=latency_ms,
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
                repaired=not content.strip().startswith("{"),
            )

        raise last_error or LLMBadResponse(f"{self.name} produced no usable response")

    async def aclose(self) -> None:
        await self._client.aclose()
