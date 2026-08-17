"""Additive AI provider extensions (Batch 01 Part 3).

Extends the existing provider system (``clients.py``) with:
  - OpenRouter client (OpenAI-compatible aggregator)
  - z.ai / GLM (Zhipu) client
  - streaming support for OpenAI-compatible style providers
  - cost / token tracking with per-provider usage stats
  - provider health checks (latency + reachability)
  - explicit provider priority ordering for failover

Everything here is additive: existing clients, the ``ManagedProvider`` wrapper
and the failover manager in ``clients.py`` are imported but never modified.
"""
import json
import threading
import time

import httpx

from ...config import settings
from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.provider_framework import providers
from .clients import (
    BaseLLMClient,
    CircuitBreaker,
    LLMError,
    ManagedProvider,
    RateLimiter,
    _parse_model_json,
    AzureOpenAIClient,
)

DEFAULT_TIMEOUT = float(settings.AI_TIMEOUT_SECONDS or 120)
DEFAULT_RETRIES = int(settings.AI_MAX_RETRIES or 3)
DEFAULT_BREAKER_FAILURES = int(settings.AI_CIRCUIT_BREAKER_FAILURES or 5)
DEFAULT_BREAKER_RESET = float(settings.AI_CIRCUIT_BREAKER_RESET_SECONDS or 60)
DEFAULT_RATE_LIMIT_RPM = int(settings.AI_RATE_LIMIT_RPM or 30)

# Rough USD per 1K tokens per provider for cost accounting (prompt/completion).
# Extend this table additively; unknown providers fall back to a 0.0 cost.
COST_PER_1K_TOKENS = {
    "openrouter": {"prompt": 0.0010, "completion": 0.0020},
    "glm": {"prompt": 0.0010, "completion": 0.0020},
    "lmstudio": {"prompt": 0.0, "completion": 0.0},
    "huggingface": {"prompt": 0.0010, "completion": 0.0020},
    "custom-http": {"prompt": 0.0010, "completion": 0.0020},
    "openai-compatible": {"prompt": 0.0010, "completion": 0.0020},
    "anthropic": {"prompt": 0.0030, "completion": 0.0150},
    "gemini": {"prompt": 0.0005, "completion": 0.0015},
}


class CostTracker:
    """Accumulates token usage and estimated USD cost per provider."""

    def __init__(self, enabled=None):
        self.enabled = settings.AI_COST_TRACKING if enabled is None else bool(enabled)
        self._lock = threading.Lock()
        self._stats = {}

    def _row(self, provider_id):
        row = self._stats.setdefault(
            provider_id,
            {"calls": 0, "promptTokens": 0, "completionTokens": 0, "totalTokens": 0, "estimatedCostUsd": 0.0},
        )
        return row

    def record(self, provider_id, usage=None):
        usage = usage or {}
        if not self.enabled:
            return
        with self._lock:
            row = self._row(provider_id)
            prompt = int(usage.get("prompt_tokens") or usage.get("promptTokens") or 0)
            completion = int(usage.get("completion_tokens") or usage.get("completionTokens") or 0)
            row["calls"] += 1
            row["promptTokens"] += prompt
            row["completionTokens"] += completion
            row["totalTokens"] += prompt + completion
            rate = COST_PER_1K_TOKENS.get(provider_id, {"prompt": 0.0, "completion": 0.0})
            row["estimatedCostUsd"] += (prompt / 1000.0) * rate["prompt"] + (completion / 1000.0) * rate["completion"]
        event_bus.emit("ai:usage", {"provider": provider_id, "promptTokens": prompt, "completionTokens": completion})

    def status(self):
        with self._lock:
            return {
                "enabled": self.enabled,
                "providers": {pid: dict(row) for pid, row in self._stats.items()},
            }


cost_tracker = CostTracker()


class OpenRouterClient(BaseLLMClient):
    """OpenRouter chat completions (OpenAI-compatible surface)."""

    id = "openrouter"
    name = "OpenRouter"
    url = None
    api_key = None
    model = None

    def __init__(self, api_key, model="deepseek/deepseek-chat", timeout=DEFAULT_TIMEOUT, extra_headers=None):
        super().__init__(timeout)
        self.api_key = api_key
        self.model = model
        self.extra_headers = dict(extra_headers or {})

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }

    def _endpoint(self):
        return "https://openrouter.ai/api/v1/chat/completions"

    def complete(self, messages, model=None, temperature=0.2, max_tokens=2000):
        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        with httpx.Client(timeout=self.timeout) as client:
            res = client.post(self._endpoint(), json=payload, headers=self._headers())
            res.raise_for_status()
            data = res.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage") or {}
        cost_tracker.record(self.id, usage)
        return {"text": text, "model": data.get("model"), "usage": usage, "provider": self.id}

    def stream(self, messages, model=None, temperature=0.2, max_tokens=2000):
        """Yield text deltas from a streaming completion."""
        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        with httpx.Client(timeout=self.timeout) as client:
            with client.stream("POST", self._endpoint(), json=payload, headers=self._headers()) as res:
                res.raise_for_status()
                for line in res.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        obj = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    delta = (obj.get("choices") or [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        yield delta

    def health(self):
        started = time.monotonic()
        with httpx.Client(timeout=min(self.timeout, 10.0)) as client:
            res = client.get("https://openrouter.ai/api/v1/models", headers={"Authorization": f"Bearer {self.api_key}"})
            ok = res.status_code < 500
        return {"ok": ok, "latencyMs": int((time.monotonic() - started) * 1000), "status": res.status_code}


class GLMClient(BaseLLMClient):
    """z.ai / Zhipu GLM chat completions (OpenAI-compatible surface)."""

    id = "glm"
    name = "z.ai / GLM"
    url = None
    api_key = None
    model = None

    def __init__(self, api_key, model="glm-4-plus", timeout=DEFAULT_TIMEOUT):
        super().__init__(timeout)
        self.api_key = api_key
        self.model = model

    def _endpoint(self):
        return "https://open.bigmodel.cn/api/paas/v4/chat/completions"

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def complete(self, messages, model=None, temperature=0.2, max_tokens=2000):
        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        with httpx.Client(timeout=self.timeout) as client:
            res = client.post(self._endpoint(), json=payload, headers=self._headers())
            res.raise_for_status()
            data = res.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage") or {}
        cost_tracker.record(self.id, usage)
        return {"text": text, "model": data.get("model"), "usage": usage, "provider": self.id}

    def stream(self, messages, model=None, temperature=0.2, max_tokens=2000):
        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        with httpx.Client(timeout=self.timeout) as client:
            with client.stream("POST", self._endpoint(), json=payload, headers=self._headers()) as res:
                res.raise_for_status()
                for line in res.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        obj = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    delta = (obj.get("choices") or [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        yield delta

    def health(self):
        started = time.monotonic()
        with httpx.Client(timeout=min(self.timeout, 10.0)) as client:
            res = client.get("https://open.bigmodel.cn/api/paas/v4/model/glm", headers=self._headers())
            ok = res.status_code < 500
        return {"ok": ok, "latencyMs": int((time.monotonic() - started) * 1000), "status": res.status_code}


class LMStudioClient(OpenRouterClient):
    """LM Studio local server (OpenAI-compatible /v1 surface, no API key).

    Defaults to the standard LM Studio endpoint http://localhost:1234/v1 and
    exposes a ``/v1/models`` health check.
    """

    id = "lmstudio"
    name = "LM Studio (local)"
    _default_base_url = "http://localhost:1234/v1"
    _default_model = "local-model"

    def __init__(self, base_url=None, model=None, timeout=DEFAULT_TIMEOUT):
        super().__init__(api_key="", model=model or self._default_model, timeout=timeout)
        self.url = (base_url or self._default_base_url).rstrip("/") + "/chat/completions"
        self.model = model or self._default_model

    def _headers(self):
        return {"Content-Type": "application/json"}

    def _endpoint(self):
        return self.url.replace("/chat/completions", "/models")

    def health(self):
        started = time.monotonic()
        with httpx.Client(timeout=min(self.timeout, 10.0)) as client:
            res = client.get(self._endpoint())
            ok = res.status_code < 500
        return {"ok": ok, "latencyMs": int((time.monotonic() - started) * 1000), "status": res.status_code}


class HuggingFaceClient(OpenRouterClient):
    """HuggingFace Inference Endpoints / TGI (OpenAI-compatible surface).

    Typically deployed on Hugging Face or self-hosted text-generation-inference.
    """

    id = "huggingface"
    name = "HuggingFace (Inference/TGI)"
    _default_base_url = "https://api-inference.huggingface.co/v1"
    _default_model = "microsoft/Phi-3-mini-4k-instruct"

    def __init__(self, api_key, base_url=None, model=None, timeout=DEFAULT_TIMEOUT):
        super().__init__(api_key=api_key, model=model or self._default_model, timeout=timeout)
        self.url = (base_url or self._default_base_url).rstrip("/") + "/chat/completions"
        self.model = model or self._default_model


class CustomHTTPClient(OpenRouterClient):
    """Generic OpenAI-compatible HTTP endpoint with explicit base URL + optional key.

    Use for any self-hosted gateway, proxy or vendor exposing an OpenAI-style
    ``/v1/chat/completions`` route (vLLM, Ollama, Together, Groq, ...).
    """

    id = "custom-http"
    name = "Custom HTTP (OpenAI-compatible)"
    _default_base_url = "http://localhost:8000/v1"
    _default_model = "model"

    def __init__(self, base_url=None, api_key=None, model=None, timeout=DEFAULT_TIMEOUT):
        super().__init__(api_key=api_key or "", model=model or self._default_model, timeout=timeout)
        self.url = (base_url or self._default_base_url).rstrip("/") + "/chat/completions"
        self.model = model or self._default_model


class StreamingManagedProvider(ManagedProvider):
    """ManagedProvider extended with streaming and cost tracking.

    Inherits retry / breaker / limiter logic unchanged; adds ``stream_reason``
    that yields parsed JSON fragments and records usage when available.
    """

    def __init__(self, client, retries=DEFAULT_RETRIES, breaker=None, limiter=None):
        super().__init__(client, retries=retries, breaker=breaker, limiter=limiter)

    def stream_reason(self, context, on_delta=None):
        if not hasattr(self.client, "stream"):
            raise LLMError(f"{self.client.id}: provider does not support streaming")
        self.stats["calls"] += 1
        if not self.breaker.allow():
            self.stats["failures"] += 1
            raise LLMError(f"{self.client.id}: circuit breaker open")
        if not self.limiter.wait_and_acquire():
            self.stats["rateLimited"] += 1
            self.stats["failures"] += 1
            raise LLMError(f"{self.client.id}: rate limit exceeded")
        from .clients import _build_messages

        last_error = None
        for attempt in range(self.retries + 1):
            try:
                chunks = []
                for delta in self.client.stream(_build_messages(context)):
                    chunks.append(delta)
                    if on_delta:
                        on_delta(delta)
                text = "".join(chunks)
                parsed = _parse_model_json(text, self.client.id)
                self.breaker.record_success()
                self.stats["successes"] += 1
                return {**parsed, "streamed": True}
            except Exception as exc:  # noqa: BLE001 - transport failures retry
                self.breaker.record_failure()
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2 ** attempt, 8.0))
        self.stats["failures"] += 1
        raise LLMError(f"{self.client.id}: streaming retries failed: {last_error}")


# --------------------------------------------------------------------------- #
# Additive registration
# --------------------------------------------------------------------------- #
def _env(key, default=""):
    import os

    return os.environ.get(key, default)


def build_extension_clients():
    """Return a list of ManagedProvider extension instances (empty keys -> none)."""
    managed = []
    openrouter_key = _env("USER_LLM_OPENROUTER_API_KEY") or settings.USER_LLM_OPENROUTER_API_KEY
    if openrouter_key:
        managed.append(StreamingManagedProvider(OpenRouterClient(
            openrouter_key,
            model=_env("USER_LLM_OPENROUTER_MODEL") or settings.USER_LLM_OPENROUTER_MODEL,
        )))
    glm_key = _env("USER_LLM_GLM_API_KEY") or settings.USER_LLM_GLM_API_KEY
    if glm_key:
        managed.append(StreamingManagedProvider(GLMClient(
            glm_key,
            model=_env("USER_LLM_GLM_MODEL") or settings.USER_LLM_GLM_MODEL,
        )))
    lmstudio_url = _env("USER_LLM_LMSTUDIO_BASE_URL") or settings.USER_LLM_LMSTUDIO_BASE_URL
    if lmstudio_url:
        managed.append(StreamingManagedProvider(LMStudioClient(
            lmstudio_url,
            model=_env("USER_LLM_LMSTUDIO_MODEL") or settings.USER_LLM_LMSTUDIO_MODEL,
        )))
    hf_key = _env("USER_LLM_HUGGINGFACE_API_KEY") or settings.USER_LLM_HUGGINGFACE_API_KEY
    hf_url = _env("USER_LLM_HUGGINGFACE_BASE_URL") or settings.USER_LLM_HUGGINGFACE_BASE_URL
    if hf_key or hf_url:
        managed.append(StreamingManagedProvider(HuggingFaceClient(
            hf_key,
            base_url=hf_url or None,
            model=_env("USER_LLM_HUGGINGFACE_MODEL") or settings.USER_LLM_HUGGINGFACE_MODEL,
        )))
    custom_url = _env("USER_LLM_CUSTOM_BASE_URL") or settings.USER_LLM_CUSTOM_BASE_URL
    if custom_url:
        managed.append(StreamingManagedProvider(CustomHTTPClient(
            custom_url,
            api_key=_env("USER_LLM_CUSTOM_API_KEY") or settings.USER_LLM_CUSTOM_API_KEY,
            model=_env("USER_LLM_CUSTOM_MODEL") or settings.USER_LLM_CUSTOM_MODEL,
        )))
    azure_key = _env("USER_LLM_AZURE_API_KEY") or settings.USER_LLM_AZURE_API_KEY
    azure_endpoint = _env("USER_LLM_AZURE_ENDPOINT") or settings.USER_LLM_AZURE_ENDPOINT
    if azure_key and azure_endpoint:
        managed.append(ManagedProvider(AzureOpenAIClient(
            azure_key,
            endpoint=azure_endpoint,
            deployment=_env("USER_LLM_AZURE_DEPLOYMENT") or settings.USER_LLM_AZURE_DEPLOYMENT,
            api_version=_env("USER_LLM_AZURE_API_VERSION") or settings.USER_LLM_AZURE_API_VERSION,
            model=_env("USER_LLM_AZURE_MODEL") or settings.USER_LLM_AZURE_MODEL or None,
        )))
    return managed


def _register_extensions(managed):
    for mp in managed:
        if providers.get(mp.id):
            continue
        providers.register({
            "id": mp.id,
            "category": "ai-model",
            "name": mp.client.name,
            "model": mp.client.model,
            "enabled": True,
            "reason": mp.reason,
            "stream": mp.stream_reason if hasattr(mp, "stream_reason") else None,
            "health": getattr(mp.client, "health", None),
        })


def init_provider_extensions():
    """Register additive providers and merge them into the running failover chain."""
    managed = build_extension_clients()
    _register_extensions(managed)
    if managed:
        from .clients import ai_provider_manager  # lazy: avoid import cycle
        if ai_provider_manager is not None:
            existing = {mp.id for mp in ai_provider_manager.managed}
            additions = [mp for mp in managed if mp.id not in existing]
            if additions:
                # Keep the deterministic fallback last in the chain so real
                # providers are always tried before the heuristic.
                base = [mp for mp in ai_provider_manager.managed if mp.id != "local-fallback"]
                fallback = [mp for mp in ai_provider_manager.managed if mp.id == "local-fallback"]
                ai_provider_manager.managed = base + additions + fallback
        logger.info(f"AI provider extensions initialized: {[mp.id for mp in managed]}")
        event_bus.emit("ai:extensions-ready", {"providers": [mp.id for mp in managed]})
    return managed


def reorder_providers_by_priority(manager, priority_csv=None):
    """Additively reorder ``manager.managed`` by explicit priority (best-first).

    Unknown ids keep their existing relative order after the prioritized ones.
    """
    if manager is None:
        return manager
    order = (priority_csv or settings.AI_PROVIDER_PRIORITY or "").strip()
    if not order:
        return manager
    preferred = [p.strip() for p in order.split(",") if p.strip()]
    if not preferred:
        return manager
    by_id = {mp.id: mp for mp in manager.managed}
    ordered = [by_id[pid] for pid in preferred if pid in by_id]
    ordered_ids = {mp.id for mp in ordered}
    rest = [mp for mp in manager.managed if mp.id not in ordered_ids]
    manager.managed = ordered + rest
    event_bus.emit("ai:priority-reordered", {"priority": preferred})
    return manager


def provider_health_status():
    """Per-provider health snapshot for the AI health endpoint."""
    result = {}
    for p in providers.list("ai-model"):
        health = p.get("health")
        if callable(health):
            try:
                result[p["id"]] = health()
            except Exception as exc:  # noqa: BLE001 - health probes must never crash
                result[p["id"]] = {"ok": False, "error": str(exc)}
        else:
            result[p["id"]] = {"ok": None, "reason": "no-health-probe"}
    return result
