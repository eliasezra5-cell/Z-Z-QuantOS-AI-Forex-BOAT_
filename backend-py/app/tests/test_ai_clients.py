"""Unit tests for the AI provider clients (resilience + failover + request building).

No real network calls are made; httpx is mocked.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test")

from unittest import mock  # noqa: E402

import pytest  # noqa: E402

from app.modules.ai.clients import (  # noqa: E402
    AnthropicClient,
    AzureOpenAIClient,
    CircuitBreaker,
    GeminiClient,
    LLMError,
    ManagedProvider,
    OpenAICompatibleClient,
    ProviderManager,
    RateLimiter,
    _build_messages,
    _heuristic_reason,
    _parse_model_json,
    init_ai_clients,
    run_llm_reasoning,
)


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeClientContext:
    """Replaces httpx.Client; records calls and returns canned responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if not self._responses:
            raise RuntimeError("no more canned responses")
        return self._responses.pop(0)


def _mock_httpx(responses):
    fake = FakeClientContext(responses)
    patcher = mock.patch("httpx.Client", return_value=fake)
    return patcher, fake


# --------------------------------------------------------------------------- #
# Circuit breaker
# --------------------------------------------------------------------------- #
def test_breaker_allows_until_threshold():
    b = CircuitBreaker(failures=3, reset_seconds=60)
    assert b.allow()
    b.record_failure()
    b.record_failure()
    assert b.allow()  # 2 < 3
    b.record_failure()
    assert not b.allow()  # now open


def test_breaker_recovers_after_cooldown():
    b = CircuitBreaker(failures=2, reset_seconds=1)
    b.record_failure(now=0.0)
    b.record_failure(now=0.0)
    assert not b.allow(now=0.5)
    assert b.allow(now=2.0)  # cooldown elapsed -> half-open/closed


def test_breaker_success_resets_failures():
    b = CircuitBreaker(failures=3, reset_seconds=60)
    b.record_failure()
    b.record_success()
    b.record_failure()
    b.record_failure()
    assert b.allow()  # success cleared the first failure


# --------------------------------------------------------------------------- #
# Rate limiter
# --------------------------------------------------------------------------- #
def test_rate_limiter_enforces_window():
    r = RateLimiter(rpm=3)
    now = 100.0
    assert r.acquire(now)
    assert r.acquire(now)
    assert r.acquire(now)
    assert not r.acquire(now)
    assert r.acquire(now + 61.0)  # window slid


def test_rate_limiter_wait_timeout():
    r = RateLimiter(rpm=1)
    r.acquire()
    assert r.wait_and_acquire(timeout=0.05) is False


# --------------------------------------------------------------------------- #
# Request building + response parsing
# --------------------------------------------------------------------------- #
def test_build_messages_has_system_and_context():
    msgs = _build_messages({"symbol": "XAUUSD", "summary": {"price": 4300, "trend": "bullish"}})
    assert msgs[0]["role"] == "system"
    assert "XAUUSD" in msgs[1]["content"]
    assert "4300" in msgs[1]["content"]


def test_parse_model_json_valid():
    out = _parse_model_json('{"direction": "buy", "confidence": 0.87, "reasoning": "strong"}', "openai-compatible")
    assert out["direction"] == "buy"
    assert out["confidence"] == 0.87
    assert out["reasoning"] == "strong"
    assert out["model"] == "openai-compatible"


def test_parse_model_json_invalid_direction_clamped():
    out = _parse_model_json('{"direction": "moon", "confidence": 5, "reasoning": ""}', "gemini")
    assert out["direction"] == "neutral"
    assert out["confidence"] == 1.0


def test_parse_model_json_non_json_raises():
    with pytest.raises(LLMError):
        _parse_model_json("sorry I cannot do that", "anthropic")


# --------------------------------------------------------------------------- #
# Transport request payloads (mocked)
# --------------------------------------------------------------------------- #
def test_openai_payload_and_auth():
    patcher, fake = _mock_httpx([
        FakeResponse({"choices": [{"message": {"content": '{"direction":"sell","confidence":0.6,"reasoning":"r"}'}}], "model": "deepseek-chat"}),
    ])
    with patcher:
        client = OpenAICompatibleClient(base_url="http://host/v1", api_key="sk-test", model="deepseek-chat")
        client.complete([{"role": "user", "content": "hi"}])
    call = fake.calls[0]
    assert call["url"] == "http://host/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-test"
    assert call["json"]["model"] == "deepseek-chat"


def test_anthropic_uses_x_api_key():
    patcher, fake = _mock_httpx([
        FakeResponse({"content": [{"type": "text", "text": '{"direction":"buy","confidence":0.9,"reasoning":"claude"}'}], "model": "claude-x"}),
    ])
    with patcher:
        client = AnthropicClient(api_key="sk-ant-test", model="claude-x")
        client.complete([{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}])
    call = fake.calls[0]
    assert call["headers"]["x-api-key"] == "sk-ant-test"
    assert call["json"]["system"] == "sys"
    assert call["json"]["messages"] == [{"role": "user", "content": "hi"}]


def test_gemini_payload_shape():
    patcher, fake = _mock_httpx([
        FakeResponse({"candidates": [{"content": {"parts": [{"text": '{"direction":"neutral","confidence":0.5,"reasoning":"g"}'}]}}], "usageMetadata": {}}),
    ])
    with patcher:
        client = GeminiClient(api_key="gem-test", model="gemini-2.0-flash")
        client.complete([{"role": "user", "content": "hi"}])
    call = fake.calls[0]
    assert "generativelanguage.googleapis.com" in call["url"]
    assert call["headers"]["x-goog-api-key"] == "gem-test"
    assert call["json"]["generationConfig"]["maxOutputTokens"] == 2000


def test_azure_url_auth_and_payload():
    patcher, fake = _mock_httpx([
        FakeResponse({"choices": [{"message": {"content": '{"direction":"sell","confidence":0.7,"reasoning":"a"}'}}], "model": "gpt-4o"}),
    ])
    with patcher:
        client = AzureOpenAIClient(
            api_key="az-test-key",
            endpoint="https://my-resource.openai.azure.com/",
            deployment="my-gpt4",
            api_version="2024-06-01",
        )
        client.complete([{"role": "user", "content": "hi"}])
    call = fake.calls[0]
    assert "/openai/deployments/my-gpt4/chat/completions" in call["url"]
    assert "api-version=2024-06-01" in call["url"]
    assert call["headers"]["api-key"] == "az-test-key"
    assert "model" not in call["json"]
    assert call["json"]["messages"] == [{"role": "user", "content": "hi"}]


def test_azure_returns_deployment_model_metadata_fallback():
    patcher, fake = _mock_httpx([
        FakeResponse({"choices": [{"message": {"content": "hi"}}]}),  # no "model" key in response
    ])
    with patcher:
        client = AzureOpenAIClient(
            api_key="az-test-key",
            endpoint="https://my-resource.openai.azure.com",
            deployment="gpt-4o-deploy",
        )
        out = client.complete([{"role": "user", "content": "hi"}])
    assert out["text"] == "hi"
    assert out["model"] == "gpt-4o-deploy"
    assert out["provider"] == "azure-openai"


def test_azure_endpoint_trailing_slash_normalized():
    client = AzureOpenAIClient(api_key="k", endpoint="https://x.openai.azure.com/", deployment="d")
    assert client._url().startswith("https://x.openai.azure.com/openai/deployments/d/chat/completions?")



# --------------------------------------------------------------------------- #
# Retry / failover / end-to-end
# --------------------------------------------------------------------------- #
def test_managed_provider_retries_then_succeeds():
    patcher, fake = _mock_httpx([
        FakeResponse({}, status=500),
        FakeResponse({"choices": [{"message": {"content": '{"direction":"buy","confidence":0.8,"reasoning":"ok"}'}}], "model": "m"}),
    ])
    with patcher:
        client = OpenAICompatibleClient(base_url="http://host/v1", model="m")
        mp = ManagedProvider(client, retries=2)
        result = mp.reason({"summary": {"price": 1}})
    assert result["direction"] == "buy"
    assert mp.stats["successes"] == 1
    assert len(fake.calls) == 2


def test_managed_provider_gives_up_after_retries():
    patcher, fake = _mock_httpx([FakeResponse({}, status=500) for _ in range(4)])
    with patcher:
        client = OpenAICompatibleClient(base_url="http://host/v1", model="m")
        mp = ManagedProvider(client, retries=1)
        with pytest.raises(LLMError):
            mp.reason({"summary": {}})
    assert len(fake.calls) == 2


def test_failover_uses_second_provider():
    class AlwaysFail:
        id = "fail"
        name = "Fail"
        model = "x"

        def complete(self, messages, **kw):
            raise RuntimeError("boom")

    class AlwaysOk:
        id = "ok"
        name = "Ok"
        model = "y"

        def complete(self, messages, **kw):
            return {"text": '{"direction":"buy","confidence":0.7,"reasoning":"ok"}', "model": "y", "usage": {}}

    manager = ProviderManager([
        ManagedProvider(AlwaysFail(), retries=0),
        ManagedProvider(AlwaysOk(), retries=0),
    ])
    result = manager.reason({"summary": {}})
    assert result["direction"] == "buy"


def test_run_llm_reasoning_falls_back_to_local_heuristic():
    init_ai_clients()
    result = run_llm_reasoning({"symbol": "XAUUSD", "summary": {"price": 4300, "trend": "bullish"}, "news": [{"sentiment": 0.5}]})
    assert result["direction"] in ("buy", "sell", "neutral")
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["provider"] == "local-fallback"


def test_heuristic_detects_buy_bias():
    msgs = [{"role": "user", "content": "buy signal bullish risk-on strong buy"}]
    out = _heuristic_reason(msgs)
    assert out["direction"] == "buy"
    assert out["confidence"] >= 0.4
