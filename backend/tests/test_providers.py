"""Provider wire-format tests, run against a mock transport (no API key needed)."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import LLMAuthError, LLMBadResponse, LLMRateLimited
from app.llm.openai_provider import OpenAICompatibleProvider, _strictify
from app.llm.schemas import INTERVIEW_QUESTION_SCHEMA

QUESTION = {"question": "What broke first?", "acknowledgement": "", "internal_note": "probe"}


def mount(provider, handler):
    provider._client = httpx.AsyncClient(
        base_url=str(provider._client.base_url), transport=httpx.MockTransport(handler)
    )
    return provider


def call(provider):
    return asyncio.run(
        provider.structured(
            system="sys", user="usr", schema=INTERVIEW_QUESTION_SCHEMA,
            schema_name="interview_question",
        )
    )


# --------------------------------------------------------------------------
# Anthropic
# --------------------------------------------------------------------------
def anthropic(handler):
    return mount(AnthropicProvider("key", "claude-x", "https://api.anthropic.com", 10.0), handler)


def test_anthropic_forces_a_tool_call_and_reads_its_input():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "content": [{"type": "tool_use", "name": "interview_question", "input": QUESTION}],
                "usage": {"input_tokens": 120, "output_tokens": 30},
            },
        )

    result = call(anthropic(handler))
    assert captured["tool_choice"] == {"type": "tool", "name": "interview_question"}
    assert captured["system"] == "sys"
    assert captured["messages"][0]["role"] == "user"
    assert result.data["question"] == "What broke first?"
    assert result.input_tokens == 120 and result.output_tokens == 30


def test_anthropic_falls_back_to_text_json():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"content": [{"type": "text", "text": f"```json\n{json.dumps(QUESTION)}\n```"}]}
        )

    result = call(anthropic(handler))
    assert result.repaired and result.data["question"]


@pytest.mark.parametrize(
    "status,exc",
    [(401, LLMAuthError), (429, LLMRateLimited), (400, LLMBadResponse)],
)
def test_anthropic_error_mapping(status, exc):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "nope"})

    with pytest.raises(exc):
        call(anthropic(handler))


def test_anthropic_empty_content_is_an_error():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"content": []})

    with pytest.raises(LLMBadResponse):
        call(anthropic(handler))


# --------------------------------------------------------------------------
# OpenAI-compatible
# --------------------------------------------------------------------------
def openai(handler, **kwargs):
    provider = OpenAICompatibleProvider(
        name="openai", api_key="key", model="gpt-x", base_url="https://api.openai.com/v1",
        timeout=10.0, **kwargs,
    )
    return mount(provider, handler)


def test_openai_uses_strict_json_schema_first():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body["response_format"]["type"])
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(QUESTION)}}],
                "usage": {"prompt_tokens": 90, "completion_tokens": 20},
            },
        )

    result = call(openai(handler))
    assert seen == ["json_schema"]
    assert result.data["question"] == "What broke first?"


def test_openai_downgrades_when_json_schema_is_rejected():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        kind = body["response_format"]["type"]
        seen.append(kind)
        if kind == "json_schema":
            return httpx.Response(400, text="response_format not supported")
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(QUESTION)}}]})

    result = call(openai(handler))
    assert seen == ["json_schema", "json_object"]
    assert result.data["question"]


def test_openai_unparseable_content_raises():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "I'd rather not."}}]})

    with pytest.raises(LLMBadResponse):
        call(openai(handler, supports_json_schema=False))


def test_strictify_marks_every_property_required():
    strict = _strictify(INTERVIEW_QUESTION_SCHEMA)
    assert set(strict["required"]) == set(strict["properties"])
    assert strict["additionalProperties"] is False
