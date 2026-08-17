"""Tests for Phase 5 (Batch 01): LMStudio / HuggingFace / Custom HTTP adapters and their registration."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_phase5_test")

from unittest import mock  # noqa: E402

from app.modules.ai.provider_extensions import (  # noqa: E402
    CustomHTTPClient,
    HuggingFaceClient,
    LMStudioClient,
    build_extension_clients,
)
from app.modules.ai.clients import BaseLLMClient  # noqa: E402


def _fake_response(json_body, status=200):
    resp = mock.Mock()
    resp.status_code = status
    resp.raise_for_status = mock.Mock()
    resp.json = mock.Mock(return_value=json_body)
    return resp


def test_lmstudio_is_openai_compatible_subclass():
    assert issubclass(LMStudioClient, BaseLLMClient)
    c = LMStudioClient()
    assert c.id == "lmstudio"
    assert c.url == "http://localhost:1234/v1/chat/completions"
    assert c.api_key is None or c.api_key == ""
    assert c.model == "local-model"


def test_lmstudio_custom_url():
    c = LMStudioClient(base_url="http://127.0.0.1:9999/v1", model="llama3")
    assert c.url == "http://127.0.0.1:9999/v1/chat/completions"
    assert c.model == "llama3"


def test_huggingface_client_defaults():
    c = HuggingFaceClient(api_key="hf-test")
    assert c.id == "huggingface"
    assert c.url == "https://api-inference.huggingface.co/v1/chat/completions"
    assert c.api_key == "hf-test"


def test_custom_http_client_defaults():
    c = CustomHTTPClient()
    assert c.id == "custom-http"
    assert c.url == "http://localhost:8000/v1/chat/completions"


def test_adapters_build_headers_no_key_for_lmstudio():
    c = LMStudioClient()
    assert "Authorization" not in c._headers()


def test_complete_posts_to_endpoint():
    c = CustomHTTPClient(base_url="http://gateway/v1", model="m")
    body = {"choices": [{"message": {"content": "{\"direction\":\"buy\"}"}}], "model": "m", "usage": {"prompt_tokens": 5, "completion_tokens": 3}}
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.post.return_value = _fake_response(body)
        result = c.complete([{"role": "user", "content": "hi"}])
    assert result["provider"] == "custom-http"
    assert "buy" in result["text"]


def test_build_extension_clients_registers_adapters(monkeypatch):
    monkeypatch.setenv("USER_LLM_LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("USER_LLM_HUGGINGFACE_API_KEY", "hf-key")
    monkeypatch.setenv("USER_LLM_CUSTOM_BASE_URL", "http://gw/v1")
    managed = build_extension_clients()
    ids = [m.id for m in managed]
    assert "lmstudio" in ids
    assert "huggingface" in ids
    assert "custom-http" in ids


def test_build_extension_clients_no_keys_returns_empty(monkeypatch):
    for k in ("USER_LLM_LMSTUDIO_BASE_URL", "USER_LLM_HUGGINGFACE_API_KEY", "USER_LLM_HUGGINGFACE_BASE_URL", "USER_LLM_CUSTOM_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    managed = build_extension_clients()
    assert "lmstudio" not in [m.id for m in managed]
    assert "custom-http" not in [m.id for m in managed]
