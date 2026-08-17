"""Additive AI provider extras (Batch 02, additive only).

Extends the provider system with additional user-facing LLM providers that were
not present before. Each provider follows the same OpenAI-compatible / GLM
surface already used by ``provider_extensions.py`` and plugs into the same
failover chain, cost tracking and provider framework. Existing providers,
clients and the ``ManagedProvider`` wrapper are imported but never modified.

New providers registered when their (user-facing) key is set:
  - xai            xAI / Grok           (api.x.ai)
  - dashscope      Qwen via DashScope   (international)
  - dashscope-cn   Qwen via DashScope   (China)
  - zhipu          z.ai / GLM           (international)
  - minimax        MiniMax              (global)
  - minimax-cn     MiniMax              (China)

Configuration comes exclusively from ``USER_LLM_*`` environment variables or
``config.Settings`` — never from the agent environment.
"""
import os
import time

import httpx

from ...config import settings
from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.provider_framework import providers
from .provider_extensions import (
    COST_PER_1K_TOKENS,
    DEFAULT_TIMEOUT,
    GLMClient,
    OpenRouterClient,
    StreamingManagedProvider,
)

# Extend the shared per-provider cost table additively. Unknown providers still
# fall back to 0.0 cost via the parent module's table lookup.
COST_PER_1K_TOKENS.update({
    "xai": {"prompt": 0.0030, "completion": 0.0150},
    "dashscope": {"prompt": 0.0004, "completion": 0.0012},
    "dashscope-cn": {"prompt": 0.0004, "completion": 0.0012},
    "zhipu": {"prompt": 0.0010, "completion": 0.0020},
    "minimax": {"prompt": 0.0005, "completion": 0.0015},
    "minimax-cn": {"prompt": 0.0005, "completion": 0.0015},
    "nvidia": {"prompt": 0.0, "completion": 0.0},
})


def _env(key, default=""):
    return os.environ.get(key, default)


class OpenAICompatibleVendorClient(OpenRouterClient):
    """OpenAI-compatible vendor client with an explicit base URL.

    Unlike ``CustomHTTPClient`` (which reuses ``self.url`` for health probes),
    this keeps ``_endpoint()`` pointing at the ``/chat/completions`` route so
    the inherited ``complete`` / ``stream`` calls hit the right path.
    """

    id = "generic-vendor"
    name = "Generic vendor (OpenAI-compatible)"
    _default_base_url = "http://localhost:8000/v1"
    _default_model = "model"

    def __init__(self, api_key, base_url=None, model=None, timeout=DEFAULT_TIMEOUT):
        super().__init__(api_key=api_key or "", model=model or self._default_model, timeout=timeout)
        self.url = (base_url or self._default_base_url).rstrip("/") + "/chat/completions"
        self.model = model or self._default_model

    def _endpoint(self):
        return self.url

    def health(self):
        started = time.monotonic()
        with httpx.Client(timeout=min(self.timeout, 10.0)) as client:
            res = client.get(self.url.replace("/chat/completions", "/models"))
            ok = res.status_code < 500
        return {"ok": ok, "latencyMs": int((time.monotonic() - started) * 1000), "status": res.status_code}


class XAIClient(OpenAICompatibleVendorClient):
    """xAI / Grok chat completions (OpenAI-compatible surface)."""

    id = "xai"
    name = "xAI (Grok)"
    _default_base_url = "https://api.x.ai/v1"
    _default_model = "grok-3"


class DashScopeClient(OpenAICompatibleVendorClient):
    """Alibaba Qwen via DashScope international endpoint (OpenAI-compatible)."""

    id = "dashscope"
    name = "Qwen via DashScope (International)"
    _default_base_url = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    _default_model = "qwen-plus"


class DashScopeCNClient(OpenAICompatibleVendorClient):
    """Alibaba Qwen via DashScope China endpoint (OpenAI-compatible)."""

    id = "dashscope-cn"
    name = "Qwen via DashScope (China)"
    _default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    _default_model = "qwen-plus"


class ZHIPUIntlClient(GLMClient):
    """z.ai / GLM international endpoint (same protocol as BigModel)."""

    id = "zhipu"
    name = "z.ai / GLM (International)"
    _default_base_url = "https://api.z.ai/api/paas/v4"
    _default_model = "glm-4.6"

    def __init__(self, api_key, model=None, timeout=DEFAULT_TIMEOUT):
        super().__init__(api_key, model=model or self._default_model, timeout=timeout)

    def _endpoint(self):
        return f"{self._default_base_url}/chat/completions"

    def health(self):
        started = time.monotonic()
        with httpx.Client(timeout=min(self.timeout, 10.0)) as client:
            res = client.get(f"{self._default_base_url}/model/glm", headers=self._headers())
            ok = res.status_code < 500
        return {"ok": ok, "latencyMs": int((time.monotonic() - started) * 1000), "status": res.status_code}


class MiniMaxClient(OpenAICompatibleVendorClient):
    """MiniMax global endpoint (OpenAI-compatible surface)."""

    id = "minimax"
    name = "MiniMax (Global)"
    _default_base_url = "https://api.minimax.io/v1"
    _default_model = "MiniMax-Text-01"


class MiniMaxCNClient(OpenAICompatibleVendorClient):
    """MiniMax China endpoint (OpenAI-compatible surface)."""

    id = "minimax-cn"
    name = "MiniMax (China)"
    _default_base_url = "https://api.minimaxi.com/v1"
    _default_model = "MiniMax-Text-01"


class NvidiaClient(OpenAICompatibleVendorClient):
    """NVIDIA NIM hosted models (build.nvidia.com, OpenAI-compatible surface).

    NVIDIA exposes many open models (DeepSeek-R1, Llama, Qwen, ...) through a
    single OpenAI-compatible endpoint; the exact model is selectable via the
    ``USER_LLM_NVIDIA_MODEL`` env var (or the custom-agent model name).
    """

    id = "nvidia"
    name = "NVIDIA (NIM)"
    _default_base_url = "https://integrate.api.nvidia.com/v1"
    _default_model = "deepseek-ai/deepseek-r1"


# --------------------------------------------------------------------------- #
# Additive registration
# --------------------------------------------------------------------------- #
def build_extra_clients():
    """Return a list of ManagedProvider instances for the new providers.

    Only providers whose (user-facing) key / config is set are returned, so
    with no keys configured this returns an empty list and nothing changes.
    """
    managed = []
    xai_key = _env("USER_LLM_XAI_API_KEY") or settings.USER_LLM_XAI_API_KEY
    if xai_key:
        managed.append(StreamingManagedProvider(XAIClient(
            xai_key,
            model=_env("USER_LLM_XAI_MODEL") or settings.USER_LLM_XAI_MODEL,
        )))
    dashscope_key = _env("USER_LLM_DASHSCOPE_API_KEY") or settings.USER_LLM_DASHSCOPE_API_KEY
    if dashscope_key:
        managed.append(StreamingManagedProvider(DashScopeClient(
            dashscope_key,
            model=_env("USER_LLM_DASHSCOPE_MODEL") or settings.USER_LLM_DASHSCOPE_MODEL,
        )))
    dashscope_cn_key = _env("USER_LLM_DASHSCOPE_CN_API_KEY") or settings.USER_LLM_DASHSCOPE_CN_API_KEY
    if dashscope_cn_key:
        managed.append(StreamingManagedProvider(DashScopeCNClient(
            dashscope_cn_key,
            model=_env("USER_LLM_DASHSCOPE_CN_MODEL") or settings.USER_LLM_DASHSCOPE_CN_MODEL,
        )))
    zhipu_key = _env("USER_LLM_ZHIPU_API_KEY") or settings.USER_LLM_ZHIPU_API_KEY
    if zhipu_key:
        managed.append(StreamingManagedProvider(ZHIPUIntlClient(
            zhipu_key,
            model=_env("USER_LLM_ZHIPU_MODEL") or settings.USER_LLM_ZHIPU_MODEL,
        )))
    minimax_key = _env("USER_LLM_MINIMAX_API_KEY") or settings.USER_LLM_MINIMAX_API_KEY
    if minimax_key:
        managed.append(StreamingManagedProvider(MiniMaxClient(
            minimax_key,
            model=_env("USER_LLM_MINIMAX_MODEL") or settings.USER_LLM_MINIMAX_MODEL,
        )))
    minimax_cn_key = _env("USER_LLM_MINIMAX_CN_API_KEY") or settings.USER_LLM_MINIMAX_CN_API_KEY
    if minimax_cn_key:
        managed.append(StreamingManagedProvider(MiniMaxCNClient(
            minimax_cn_key,
            model=_env("USER_LLM_MINIMAX_CN_MODEL") or settings.USER_LLM_MINIMAX_CN_MODEL,
        )))
    nvidia_key = _env("USER_LLM_NVIDIA_API_KEY") or settings.USER_LLM_NVIDIA_API_KEY
    if nvidia_key:
        managed.append(StreamingManagedProvider(NvidiaClient(
            nvidia_key,
            model=_env("USER_LLM_NVIDIA_MODEL") or settings.USER_LLM_NVIDIA_MODEL,
        )))
    return managed


def init_extra_providers():
    """Register the new providers and merge them into the running failover chain.

    Additive: existing registered providers and the deterministic fallback are
    left untouched. Returns the list of ManagedProvider instances created.
    """
    managed = build_extra_clients()
    if not managed:
        return managed
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
    logger.info(f"AI provider extras initialized: {[mp.id for mp in managed]}")
    event_bus.emit("ai:extras-ready", {"providers": [mp.id for mp in managed]})
    return managed


# --------------------------------------------------------------------------- #
# Connection status (additive reporting helper)
# --------------------------------------------------------------------------- #
_PROVIDER_NAMES = {
    "openaiCompatible": "OpenAI-compatible (DeepSeek / OpenAI / Ollama)",
    "anthropic": "Anthropic Claude",
    "gemini": "Google Gemini",
    "openrouter": "OpenRouter",
    "glm": "z.ai / GLM (BigModel CN)",
    "azure": "Azure OpenAI",
    "xai": "xAI (Grok)",
    "dashscope": "Qwen via DashScope (International)",
    "dashscope-cn": "Qwen via DashScope (China)",
    "zhipu": "z.ai / GLM (International)",
    "minimax": "MiniMax (Global)",
    "minimax-cn": "MiniMax (China)",
    "nvidia": "NVIDIA (NIM)",
}


def ai_models_status():
    """Report which AI models are configured/connected.

    Combines the env-configured brain providers (``settings.ai.providers``)
    with the dashboard-created custom agents. ``connected`` reflects whether a
    usable key (or base URL, for the OpenAI-compatible provider) is present.
    """
    providers_cfg = (settings.ai or {}).get("providers") or {}
    providers_list = []
    for pid, cfg in providers_cfg.items():
        if not isinstance(cfg, dict):
            continue
        api_key = str(cfg.get("apiKey") or "")
        base_url = str(cfg.get("baseUrl") or "")
        endpoint = str(cfg.get("endpoint") or "")
        if pid == "openaiCompatible":
            connected = bool(base_url)
        elif pid == "azure":
            connected = bool(api_key and endpoint)
        else:
            connected = bool(api_key)
        providers_list.append({
            "id": pid,
            "name": _PROVIDER_NAMES.get(pid, pid),
            "model": str(cfg.get("model") or ""),
            "connected": connected,
            "source": "env",
        })

    custom = []
    try:
        from .consensus import custom_agent_registry

        for a in custom_agent_registry.list():
            custom.append({
                "id": a.get("id"),
                "name": a.get("name"),
                "providerType": a.get("provider_type") or a.get("providerType") or "free_local",
                "model": a.get("model_name") or "default",
                "connected": bool(a.get("api_key_encrypted")),
                "enabled": bool(a.get("enabled", True)),
                "source": "custom",
            })
    except Exception as exc:  # noqa: BLE001 - reporting must never crash
        logger.warn(f"ai_models_status: custom agents unavailable: {exc}")

    return {"providers": providers_list, "customAgents": custom}
