"""Unit tests for additive AI provider extensions (Batch 01 Part 3).

Covers OpenRouter / GLM request building, streaming parsing, cost tracking,
provider health status and priority reordering. No real network calls.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test")

from unittest import mock  # noqa: E402

import pytest  # noqa: E402

from app.modules.ai.provider_extensions import (  # noqa: E402
    CostTracker,
    GLMClient,
    OpenRouterClient,
    StreamingManagedProvider,
    build_extension_clients,
    cost_tracker,
    provider_health_status,
    reorder_providers_by_priority,
)
from app.modules.ai.clients import LLMError, ManagedProvider  # noqa: E402


class FakeStreamResponse:
    def __init__(self, lines, status=200):
        self._lines = lines
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_lines(self):
        return iter(self._lines)


class FakeStreamClient:
    """Minimal httpx streaming context manager."""

    def __init__(self, lines, status=200):
        self._lines = lines
        self._status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def stream(self, method, url, json=None, headers=None):
        return FakeStreamResponse(self._lines, self._status)


def _sse_chunk(delta):
    return f"data: {delta}"


def test_openrouter_payload_and_auth():
    client = OpenRouterClient("or-key", model="deepseek/deepseek-chat")
    assert client._endpoint() == "https://openrouter.ai/api/v1/chat/completions"
    headers = client._headers()
    assert headers["Authorization"] == "Bearer or-key"
    assert "Content-Type" in headers


def test_openrouter_complete_parses_response():
    client = OpenRouterClient("or-key", model="deepseek/deepseek-chat")
    payload = {
        "choices": [{"message": {"content": '{"direction":"buy","confidence":0.9,"reasoning":"r"}'}}],
        "model": "deepseek/deepseek-chat",
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }
    fake_resp = mock.Mock()
    fake_resp.raise_for_status = lambda: None
    fake_resp.json = lambda: payload
    with mock.patch("httpx.Client") as m:
        m.return_value.__enter__.return_value.post.return_value = fake_resp
        res = client.complete([{"role": "user", "content": "hi"}])
    assert res["provider"] == "openrouter"
    assert res["text"].startswith('{"direction"')


def test_glm_complete_parses_response():
    client = GLMClient("glm-key", model="glm-4-plus")
    assert client._endpoint() == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    payload = {
        "choices": [{"message": {"content": '{"direction":"sell","confidence":0.5,"reasoning":"x"}'}}],
        "model": "glm-4-plus",
        "usage": {"prompt_tokens": 5, "completion_tokens": 5},
    }
    fake_resp = mock.Mock()
    fake_resp.raise_for_status = lambda: None
    fake_resp.json = lambda: payload
    with mock.patch("httpx.Client") as m:
        m.return_value.__enter__.return_value.post.return_value = fake_resp
        res = client.complete([{"role": "user", "content": "hi"}])
    assert res["provider"] == "glm"
    assert '{"direction":"sell"' in res["text"]


def test_streaming_managed_provider_yields_parsed_json():
    lines = [
        _sse_chunk('{"choices":[{"delta":{"content":"{\\"direction\\":\\"buy\\",\\"confidence\\":0.6,\\"reasoning\\":\\"s\\"}"}}]}'),
        _sse_chunk("[DONE]"),
    ]
    with mock.patch("httpx.Client", return_value=FakeStreamClient(lines)):
        mp = StreamingManagedProvider(OpenRouterClient("or-key"))
        result = mp.stream_reason({"summary": {}})
    assert result["direction"] == "buy"
    assert result["streamed"] is True


def test_streaming_breaks_on_failure():
    mp = StreamingManagedProvider(OpenRouterClient("or-key"), retries=0)
    with mock.patch("httpx.Client", return_value=FakeStreamClient(["data: [DONE]"])), pytest.raises(LLMError):
        mp.stream_reason({"summary": {}})


def test_cost_tracker_accumulates():
    tracker = CostTracker(enabled=True)
    tracker.record("openrouter", {"prompt_tokens": 1000, "completion_tokens": 1000})
    st = tracker.status()
    row = st["providers"]["openrouter"]
    assert row["calls"] == 1
    assert row["promptTokens"] == 1000
    assert row["totalTokens"] == 2000
    assert row["estimatedCostUsd"] > 0


def test_cost_tracker_can_be_disabled():
    tracker = CostTracker(enabled=False)
    tracker.record("openrouter", {"prompt_tokens": 1000})
    assert tracker.status()["providers"] == {}


def test_priority_reorder_puts_priority_first():
    def make(client_id):
        client = mock.Mock()
        client.id = client_id
        client.name = client_id
        client.model = client_id
        return ManagedProvider(client)

    p1 = make("fallback-a")
    p2 = make("fallback-b")
    manager = mock.Mock()
    manager.managed = [p1, p2]
    reorder_providers_by_priority(manager, priority_csv="fallback-b,fallback-a")
    assert [mp.id for mp in manager.managed] == ["fallback-b", "fallback-a"]


def test_priority_reorder_noop_without_priority():
    def make(client_id):
        client = mock.Mock()
        client.id = client_id
        client.name = client_id
        client.model = client_id
        return ManagedProvider(client)

    p1 = make("x")
    p2 = make("y")
    manager = mock.Mock()
    manager.managed = [p1, p2]
    reorder_providers_by_priority(manager, priority_csv="")
    assert [mp.id for mp in manager.managed] == ["x", "y"]


def test_build_extension_clients_no_keys():
    with mock.patch.dict(os.environ, {}, clear=False):
        for k in ("USER_LLM_OPENROUTER_API_KEY", "USER_LLM_GLM_API_KEY"):
            os.environ.pop(k, None)
        assert build_extension_clients() == []


def test_provider_health_status_never_raises():
    with mock.patch("app.modules.ai.provider_extensions.providers.list", return_value=[]):
        assert provider_health_status() == {}
