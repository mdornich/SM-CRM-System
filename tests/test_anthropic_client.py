"""AnthropicClient hardening tests use httpx.MockTransport only; no real API calls."""

from __future__ import annotations

import json

import httpx
import pytest

from relationship_intel.errors import NotConfiguredError
from relationship_intel.extraction.llm_client import AnthropicClient, make_client


def _anthropic_response(text: str) -> httpx.Response:
    return httpx.Response(200, json={"content": [{"type": "text", "text": text}]})


def test_missing_anthropic_key_raises_before_request():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _anthropic_response("{}")

    client = AnthropicClient("", transport=httpx.MockTransport(handler))
    with pytest.raises(NotConfiguredError):
        client.complete("system", "{}", {})
    assert calls == 0


def test_anthropic_json_parse_retry_succeeds_on_second_response():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return _anthropic_response("not json")
        return _anthropic_response('{"ok": true}')

    client = AnthropicClient("test-key", transport=httpx.MockTransport(handler))

    assert client.complete("system", '{"transcript": "short", "metadata": {}}', {}) == {"ok": True}
    assert len(calls) == 2
    assert "previous response was not valid JSON" in calls[1]["system"]


def test_anthropic_model_can_be_overridden_in_request():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return _anthropic_response('{"ok": true}')

    client = AnthropicClient(
        "test-key",
        model="claude-sonnet-test",
        transport=httpx.MockTransport(handler),
    )

    assert client.complete("system", '{"transcript": "short", "metadata": {}}', {}) == {"ok": True}
    assert calls[0]["model"] == "claude-sonnet-test"


def test_anthropic_blank_model_falls_back_to_default():
    client = AnthropicClient("test-key", model="   ")

    assert client.model == AnthropicClient.DEFAULT_MODEL


def test_make_client_passes_anthropic_model_override():
    client = make_client(
        "anthropic",
        anthropic_api_key="test-key",
        anthropic_model="claude-sonnet-test",
    )

    assert isinstance(client, AnthropicClient)
    assert client.model == "claude-sonnet-test"


def test_anthropic_truncates_long_transcript_before_request():
    sent_payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_payloads.append(json.loads(request.content))
        return _anthropic_response('{"ok": true}')

    client = AnthropicClient(
        "test-key",
        transport=httpx.MockTransport(handler),
        max_input_chars=20,
        max_cost_usd=1.00,
    )
    user = json.dumps({"metadata": {"title": "Long"}, "transcript": "a" * 30 + "b" * 30})

    client.complete("system", user, {})

    sent_user = json.loads(sent_payloads[0]["messages"][0]["content"])
    assert sent_user["metadata"]["transcript_truncated"] is True
    assert sent_user["metadata"]["original_transcript_chars"] == 60
    assert "transcript truncated" in sent_user["transcript"]
    assert sent_user["transcript"].startswith("a" * 10)
    assert sent_user["transcript"].endswith("b" * 10)


def test_anthropic_cost_guard_blocks_before_request():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _anthropic_response('{"ok": true}')

    client = AnthropicClient(
        "test-key",
        transport=httpx.MockTransport(handler),
        max_cost_usd=0.000001,
    )

    with pytest.raises(RuntimeError, match="exceeds configured max"):
        client.complete("system", '{"transcript": "short", "metadata": {}}', {"type": "object"})
    assert calls == 0
