"""AI Provider Clients (additive module).

Real LLM client implementations registered into the provider framework under
category ``ai-model``, with per-provider configuration, automatic failover,
retries, timeout, circuit breaker and rate limiting.

Supported providers:
  - openai-compatible  (OpenAI, DeepSeek, Ollama, vLLM, LM Studio, ...)
  - anthropic          (Anthropic Messages API)
  - gemini             (Google Gemini generateContent API)
  - local-fallback     (deterministic heuristic, always available)

Configuration comes from user-facing environment variables (``USER_LLM_*``);
nothing is hardcoded and no platform/agent keys are read. Every provider
exposes a ``reason(context)`` entry point so the framework's
``providers.call(id, "reason", context)`` pattern works unchanged.
"""
import json
import os
import re
import threading
import time

import httpx

from ...config import settings
from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.provider_framework import providers

DEFAULT_TIMEOUT = float(settings.AI_TIMEOUT_SECONDS or 120)
DEFAULT_RETRIES = int(settings.AI_MAX_RETRIES or 3)
DEFAULT_BREAKER_FAILURES = int(settings.AI_CIRCUIT_BREAKER_FAILURES or 5)
DEFAULT_BREAKER_RESET = float(settings.AI_CIRCUIT_BREAKER_RESET_SECONDS or 60)
DEFAULT_RATE_LIMIT_RPM = int(settings.AI_RATE_LIMIT_RPM or 30)

SYSTEM_PROMPT = (
    "You are the AI Brain of a gold-focused quantitative trading system. "
    "Given the market context, decide direction and confidence. "
    "Respond with STRICT JSON only: "
    '{"direction": "buy"|"sell"|"neutral", "confidence": 0.0..1.0, '
    '"reasoning": "short explanation"}'
)


class LLMError(Exception):
    """Raised when an LLM call fails after retries or is blocked."""


def _env(key, default=""):
    return os.environ.get(key, default)


# --------------------------------------------------------------------------- #
# Resilience primitives
# --------------------------------------------------------------------------- #
class CircuitBreaker:
    """Trips open after ``failures`` consecutive failures, resets after a cooldown."""

    def __init__(self, failures=DEFAULT_BREAKER_FAILURES, reset_seconds=DEFAULT_BREAKER_RESET):
        self.failures = max(1, int(failures))
        self.reset_seconds = max(1.0, float(reset_seconds))
        self._fail_count = 0
        self._open_until = 0.0
        self._lock = threading.Lock()

    def allow(self, now=None):
        now = time.monotonic() if now is None else now
        with self._lock:
            if self._open_until and now >= self._open_until:
                self._open_until = 0.0
                self._fail_count = 0
            return not self._open_until

    def record_success(self):
        with self._lock:
            self._fail_count = 0

    def record_failure(self, now=None):
        now = time.monotonic() if now is None else now
        with self._lock:
            self._fail_count += 1
            if self._fail_count >= self.failures:
                self._open_until = now + self.reset_seconds

    def status(self):
        return {
            "open": bool(self._open_until),
            "failures": self._fail_count,
            "threshold": self.failures,
            "openUntil": self._open_until,
        }


class RateLimiter:
    """Fixed-window rate limiter (requests per minute)."""

    def __init__(self, rpm=DEFAULT_RATE_LIMIT_RPM):
        self.rpm = max(1, int(rpm))
        self._slots = []
        self._lock = threading.Lock()

    def acquire(self, now=None):
        now = time.monotonic() if now is None else now
        with self._lock:
            self._slots = [t for t in self._slots if now - t < 60.0]
            if len(self._slots) >= self.rpm:
                return False
            self._slots.append(now)
            return True

    def wait_and_acquire(self, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.acquire():
                return True
            time.sleep(0.05)
        return False

    def status(self):
        return {"rpm": self.rpm, "inWindow": len(self._slots)}


# --------------------------------------------------------------------------- #
# Transport clients
# --------------------------------------------------------------------------- #
class BaseLLMClient:
    """Minimal interface: ``complete(messages) -> {text, model, usage, provider}``."""

    id = "base"
    name = "Base"
    kind = "ai-model"

    def __init__(self, timeout=DEFAULT_TIMEOUT):
        self.timeout = float(timeout)

    def complete(self, messages, model=None, temperature=0.2, max_tokens=2000):  # pragma: no cover - interface
        raise NotImplementedError


class OpenAICompatibleClient(BaseLLMClient):
    """OpenAI-compatible chat completions (OpenAI, DeepSeek, Ollama, vLLM...)."""

    id = "openai-compatible"
    name = "OpenAI-compatible"
    url = None
    api_key = None
    model = None

    def __init__(self, base_url, api_key=None, model="deepseek-chat", timeout=DEFAULT_TIMEOUT):
        super().__init__(timeout)
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key or None
        self.model = model

    def complete(self, messages, model=None, temperature=0.2, max_tokens=2000):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        with httpx.Client(timeout=self.timeout) as client:
            res = client.post(self.url, json=payload, headers=headers)
            res.raise_for_status()
            data = res.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return {"text": text, "model": data.get("model"), "usage": data.get("usage") or {}, "provider": self.id}


class AnthropicClient(BaseLLMClient):
    """Anthropic Messages API (Claude)."""

    id = "anthropic"
    name = "Anthropic Claude"
    url = "https://api.anthropic.com/v1/messages"
    api_key = None
    model = None

    def __init__(self, api_key, model="claude-sonnet-4-20250514", timeout=DEFAULT_TIMEOUT):
        super().__init__(timeout)
        self.api_key = api_key
        self.model = model

    def complete(self, messages, model=None, temperature=0.2, max_tokens=2000):
        system = "\n".join(m["content"] for m in messages if m.get("role") == "system")
        conversation = [{"role": m["role"], "content": m["content"]} for m in messages if m.get("role") in ("user", "assistant")]
        payload = {"model": model or self.model, "max_tokens": max_tokens, "temperature": temperature, "messages": conversation}
        if system:
            payload["system"] = system
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
        with httpx.Client(timeout=self.timeout) as client:
            res = client.post(self.url, json=payload, headers=headers)
            res.raise_for_status()
            data = res.json()
        text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
        return {"text": text, "model": data.get("model"), "usage": data.get("usage") or {}, "provider": self.id}


class GeminiClient(BaseLLMClient):
    """Google Gemini generateContent API."""

    id = "gemini"
    name = "Google Gemini"
    api_key = None
    model = None

    def __init__(self, api_key, model="gemini-2.0-flash", timeout=DEFAULT_TIMEOUT):
        super().__init__(timeout)
        self.api_key = api_key
        self.model = model

    def complete(self, messages, model=None, temperature=0.2, max_tokens=2000):
        model_name = model or self.model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        parts = [{"text": m["content"]} for m in messages]
        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
        with httpx.Client(timeout=self.timeout) as client:
            res = client.post(url, json=payload, headers=headers)
            res.raise_for_status()
            data = res.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            text = ""
        return {"text": text, "model": model_name, "usage": data.get("usageMetadata") or {}, "provider": self.id}


class AzureOpenAIClient(BaseLLMClient):
    """Azure OpenAI chat completions (deployment-scoped endpoint, Feature 4).

    Azure models are addressed by their *deployment* name in the URL path
    (``openai/deployments/{deployment}/chat/completions``) with the API key in
    the ``api-key`` header and an ``api-version`` query param. The deployment
    name is the model handle at the gateway, so the request body does not carry
    a ``model`` field (unlike the plain OpenAI-compatible client). Only enabled
    when the user configures ``USER_LLM_AZURE_*`` env vars — no behavior change
    for existing providers.
    """

    id = "azure-openai"
    name = "Azure OpenAI"
    endpoint = None
    deployment = None
    api_version = None
    api_key = None
    model = None

    def __init__(self, api_key, endpoint, deployment="gpt-4o", api_version="2024-06-01",
                 model=None, timeout=DEFAULT_TIMEOUT):
        super().__init__(timeout)
        self.api_key = api_key
        self.endpoint = endpoint.rstrip("/")
        self.deployment = deployment
        self.api_version = api_version
        self.model = model or deployment

    def _url(self):
        return (
            f"{self.endpoint}/openai/deployments/{self.deployment}/chat/completions"
            f"?api-version={self.api_version}"
        )

    def complete(self, messages, model=None, temperature=0.2, max_tokens=2000):
        payload = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {"Content-Type": "application/json", "api-key": self.api_key}
        with httpx.Client(timeout=self.timeout) as client:
            res = client.post(self._url(), json=payload, headers=headers)
            res.raise_for_status()
            data = res.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return {
            "text": text,
            "model": data.get("model") or self.model,
            "usage": data.get("usage") or {},
            "provider": self.id,
        }


_LOCAL_DIRECTIONS = {"buy": "buy", "bullish": "buy", "long": "buy", "sell": "sell", "bearish": "sell", "short": "sell"}


def _heuristic_reason(messages):
    """Deterministic fallback that inspects the user prompt for directional words."""
    prompt = ""
    for m in messages:
        if m.get("role") == "user":
            prompt += " " + str(m.get("content", ""))
    prompt_lower = prompt.lower()
    buy_hits = sum(prompt_lower.count(w) for w in ("buy", "bullish", "long signal", "risk-on"))
    sell_hits = sum(prompt_lower.count(w) for w in ("sell", "bearish", "short signal", "risk-off"))
    if buy_hits > sell_hits and buy_hits >= 2:
        direction = "buy"
        confidence = min(0.4 + 0.1 * buy_hits, 0.8)
    elif sell_hits > buy_hits and sell_hits >= 2:
        direction = "sell"
        confidence = min(0.4 + 0.1 * sell_hits, 0.8)
    else:
        direction = "neutral"
        confidence = 0.4
    return {
        "direction": direction,
        "confidence": round(confidence, 3),
        "reasoning": f"Local heuristic fallback (buy={buy_hits}, sell={sell_hits})",
        "model": "local-fallback",
    }


class LocalFallbackClient(BaseLLMClient):
    id = "local-fallback"
    name = "Local Heuristic Fallback"
    url = None
    api_key = None
    model = "local-fallback"

    def __init__(self, timeout=DEFAULT_TIMEOUT):
        super().__init__(timeout)

    def complete(self, messages, model=None, temperature=0.2, max_tokens=2000):
        parsed = _heuristic_reason(messages)
        return {
            "text": json.dumps(parsed),
            "model": parsed["model"],
            "usage": {},
            "provider": self.id,
        }


def _schema_aware_fallback(messages, shape, provider_id):
    """Build a schema-compliant fallback result from the deterministic heuristic.

    ``shape`` maps each required field to its default value (or a callable
    taking the heuristic base dict). ``direction`` / ``confidence`` come from
    the heuristic unless the shape declares an explicit override; ``reason`` is
    tagged so consumers can tell this is not an LLM judgment. Used only when the
    local-fallback provider is active and a strict schema parser would reject
    the generic heuristic shape.
    """
    base = _heuristic_reason(messages)
    result = {}
    for key, default in shape.items():
        if key == "direction":
            result[key] = default if isinstance(default, str) else base["direction"]
        elif key == "confidence":
            result[key] = base["confidence"] if default is None else default
        elif key == "reason":
            result[key] = f"data-driven fallback, no LLM configured: {base['reasoning']}"
        elif key == "reasoning":
            result[key] = base["reasoning"]
        elif callable(default):
            result[key] = default(base)
        else:
            result[key] = default
    result["model"] = provider_id
    return result


# --------------------------------------------------------------------------- #
# Managed provider (retry + breaker + limiter wrapper)
# --------------------------------------------------------------------------- #
def _parse_model_json(text, provider_id):
    text = (text or "").strip()
    if not text:
        raise LLMError(f"{provider_id}: empty completion")
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            data = None
    else:
        data = None
    if not isinstance(data, dict):
        raise LLMError(f"{provider_id}: model did not return valid JSON")
    direction = str(data.get("direction", "neutral")).lower()
    if direction not in ("buy", "sell", "neutral"):
        direction = "neutral"
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    reasoning = str(data.get("reasoning", ""))
    return {"direction": direction, "confidence": round(confidence, 4), "reasoning": reasoning, "model": provider_id}


def _build_messages(context):
    context = context or {}
    summary = context.get("summary") or {}
    user_prompt = (
        "Market context:\n"
        f"- symbol: {context.get('symbol', '?')}\n"
        f"- price: {summary.get('price')}\n"
        f"- trend: {summary.get('trend')}\n"
        f"- rsi: {summary.get('rsi')}\n"
        f"- avg news sentiment: {summary.get('avgNewsSentiment')}\n"
        f"- high impact events: {summary.get('highImpactEvents')}\n"
        f"- news: {context.get('newsCount') or len(context.get('news') or [])} articles\n"
        f"- macro risk-on: {summary.get('macroRiskOn', context.get('macroRiskOn'))}\n"
    )
    try:
        from .conversation import preference_context

        prefs = preference_context()
        if prefs:
            user_prompt += f"\n- user preferences: {prefs}"
    except Exception:  # noqa: BLE001 - preferences must never break inference
        pass
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


class ManagedProvider:
    """Wraps a transport client with retries, circuit breaker and rate limiting,
    exposing the framework-compatible ``reason(context)`` entry point."""

    def __init__(self, client, retries=DEFAULT_RETRIES, breaker=None, limiter=None):
        self.client = client
        self.retries = max(0, int(retries))
        self.breaker = breaker or CircuitBreaker()
        self.limiter = limiter or RateLimiter()
        self.stats = {"calls": 0, "successes": 0, "failures": 0, "rateLimited": 0}

    @property
    def id(self):
        return self.client.id

    def reason(self, context):
        from ...foundation.tracing import start_span, get_correlation_id  # lazy import

        self.stats["calls"] += 1
        if not self.breaker.allow():
            self.stats["failures"] += 1
            raise LLMError(f"{self.client.id}: circuit breaker open")
        if not self.limiter.wait_and_acquire():
            self.stats["rateLimited"] += 1
            self.stats["failures"] += 1
            raise LLMError(f"{self.client.id}: rate limit exceeded")
        last_error = None
        for attempt in range(self.retries + 1):
            started = time.monotonic()
            try:
                with start_span(
                    f"ai.inference:{self.client.id}",
                    attrs={
                        "ai.provider": self.client.id,
                        "ai.model": getattr(self.client, "model", None),
                        "correlationId": get_correlation_id(),
                        "attempt": attempt,
                    },
                ):
                    result = self.client.complete(_build_messages(context))
                latency_ms = round((time.monotonic() - started) * 1000, 1)
                self._record_latency(latency_ms, self.client.id)
                parsed = _parse_model_json(result["text"], self.client.id)
                parsed["usage"] = result.get("usage") or {}
                self.breaker.record_success()
                self.stats["successes"] += 1
                return parsed
            except Exception as exc:  # noqa: BLE001 - any transport/parse failure retries
                self.breaker.record_failure()
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2 ** attempt, 8.0))
        self.stats["failures"] += 1
        raise LLMError(f"{self.client.id}: all retries failed: {last_error}")

    def complete_custom(self, messages, parser=None, fallback_shape=None, temperature=0.2, max_tokens=2000):
        """Resilient completion with a caller-supplied prompt and parser.

        Additive entry point used by the strict-schema agents (e.g. the News
        Analysis Agent) without touching ``reason(context)``.

        ``fallback_shape`` is a schema-aware fallback map: when the active
        transport is the deterministic local-fallback provider and its generic
        heuristic shape would be rejected by ``parser``, a schema-compliant
        result is built from the heuristic + the declared defaults instead of
        failing. When ``None`` (default), the strict parser result stands and
        failures propagate as ``LLMError`` — preserving honest degradation for
        agents that must not fabricate output.
        """
        from ...foundation.tracing import start_span, get_correlation_id  # lazy import

        self.stats["calls"] += 1
        if not self.breaker.allow():
            self.stats["failures"] += 1
            raise LLMError(f"{self.client.id}: circuit breaker open")
        if not self.limiter.wait_and_acquire():
            self.stats["rateLimited"] += 1
            self.stats["failures"] += 1
            raise LLMError(f"{self.client.id}: rate limit exceeded")
        last_error = None
        for attempt in range(self.retries + 1):
            started = time.monotonic()
            try:
                with start_span(
                    f"ai.inference:{self.client.id}",
                    attrs={
                        "ai.provider": self.client.id,
                        "ai.model": getattr(self.client, "model", None),
                        "correlationId": get_correlation_id(),
                        "attempt": attempt,
                    },
                ):
                    result = self.client.complete(messages, temperature=temperature, max_tokens=max_tokens)
                latency_ms = round((time.monotonic() - started) * 1000, 1)
                self._record_latency(latency_ms, self.client.id)
                if self.client.id == "local-fallback" and fallback_shape is not None:
                    parsed = _schema_aware_fallback(messages, fallback_shape, self.client.id)
                else:
                    parsed = parser(result["text"], self.client.id) if parser else {"text": result["text"], "model": self.client.id}
                parsed["usage"] = result.get("usage") or {}
                self.breaker.record_success()
                self.stats["successes"] += 1
                return parsed
            except Exception as exc:  # noqa: BLE001 - any transport/parse failure retries
                self.breaker.record_failure()
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2 ** attempt, 8.0))
        self.stats["failures"] += 1
        raise LLMError(f"{self.client.id}: all retries failed: {last_error}")

    def _record_latency(self, latency_ms, provider):
        """Emit the AI inference latency metric (SLO: ai.inference.latency)."""
        try:
            from ...modules.observability.init import record_ai_latency  # lazy import

            record_ai_latency(provider, latency_ms)
        except Exception:  # noqa: BLE001 - metrics best effort
            pass

    def status(self):
        return {
            "id": self.id,
            "name": self.client.name,
            "model": self.client.model,
            "enabled": True,
            "breaker": self.breaker.status(),
            "limiter": self.limiter.status(),
            "stats": dict(self.stats),
        }


# --------------------------------------------------------------------------- #
# Failover manager + registration
# --------------------------------------------------------------------------- #
class ProviderManager:
    """Failover across managed providers in priority order."""

    def __init__(self, managed):
        self.managed = managed

    def reason(self, context):
        errors = []
        for mp in self.managed:
            try:
                return mp.reason(context)
            except LLMError as exc:
                errors.append(f"{mp.id}: {exc}")
                event_bus.emit("ai:provider-failure", {"provider": mp.id, "error": str(exc)})
                logger.warn(f"AI provider {mp.id} failed", meta={"error": str(exc)})
        raise LLMError("all AI providers failed: " + "; ".join(errors))

    def complete_custom(self, messages, parser=None, fallback_shape=None, temperature=0.2, max_tokens=2000):
        """Failover across managed providers with a caller-supplied prompt/parser."""
        errors = []
        for mp in self.managed:
            try:
                return mp.complete_custom(messages, parser=parser, fallback_shape=fallback_shape,
                                          temperature=temperature, max_tokens=max_tokens)
            except LLMError as exc:
                errors.append(f"{mp.id}: {exc}")
                event_bus.emit("ai:provider-failure", {"provider": mp.id, "error": str(exc)})
                logger.warn(f"AI provider {mp.id} failed", meta={"error": str(exc)})
        raise LLMError("all AI providers failed: " + "; ".join(errors))

    def status(self):
        return {"providers": [mp.status() for mp in self.managed]}


def _build_managed_providers():
    managed = []
    base_url = _env("USER_LLM_BASE_URL")
    if base_url:
        managed.append(ManagedProvider(
            OpenAICompatibleClient(
                base_url=base_url,
                api_key=_env("USER_LLM_API_KEY"),
                model=_env("USER_LLM_MODEL", "deepseek-chat"),
            )
        ))
    anthropic_key = _env("USER_LLM_ANTHROPIC_API_KEY")
    if anthropic_key:
        managed.append(ManagedProvider(AnthropicClient(
            anthropic_key,
            model=_env("USER_LLM_ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        )))
    gemini_key = _env("USER_LLM_GEMINI_API_KEY")
    if gemini_key:
        managed.append(ManagedProvider(GeminiClient(
            gemini_key,
            model=_env("USER_LLM_GEMINI_MODEL", "gemini-2.0-flash"),
        )))
    # Deterministic fallback is always last so there is always a working provider.
    managed.append(ManagedProvider(LocalFallbackClient()))
    return managed


ai_provider_manager = None


def _register_managed(managed):
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
        })


def init_ai_clients():
    global ai_provider_manager
    managed = _build_managed_providers()
    ai_provider_manager = ProviderManager(managed)
    _register_managed(managed)
    event_bus.emit("ai:clients-ready", {"providers": [mp.id for mp in managed]})
    logger.info(f"AI provider clients initialized: {[mp.id for mp in managed]}")
    return ai_provider_manager


def ai_providers_status():
    manager = ai_provider_manager
    if manager is None:
        return {"providers": [], "available": False, "reason": "not-initialized"}
    return {**manager.status(), "available": True}


def run_llm_reasoning(context):
    manager = ai_provider_manager
    if manager is None:
        raise LLMError("AI provider clients not initialized")
    result = manager.reason(context)
    result["provider"] = result["model"]
    return result
