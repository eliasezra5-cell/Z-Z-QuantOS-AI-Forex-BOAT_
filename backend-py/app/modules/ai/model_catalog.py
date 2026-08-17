"""Model catalog (Feature 4, metadata only).

Static, read-only metadata describing every model the AI layer can address per
provider — pure data: no network calls, no credentials, no file I/O, no
lifecycle state. Model lifecycle / governance is handled by
``model_registry.py``; this module only documents *what* models exist so the UI
and provider auto-detection can reason about capabilities (context window, max
output, modality) without touching a provider.

Azure OpenAI deployments are included because they are addressed by deployment
name at the gateway (see ``clients.AzureOpenAIClient``); the catalog keeps the
canonical model name alongside the deployment handle.
"""
from copy import deepcopy

MODEL_CATALOG = {
    "azure-openai": {
        "label": "Azure OpenAI",
        "kind": "chat",
        "models": [
            {"id": "gpt-4o", "name": "GPT-4o", "contextWindow": 128000, "maxOutputTokens": 16384, "modality": "chat"},
            {"id": "gpt-4o-mini", "name": "GPT-4o mini", "contextWindow": 128000, "maxOutputTokens": 16384, "modality": "chat"},
            {"id": "gpt-4", "name": "GPT-4", "contextWindow": 8192, "maxOutputTokens": 8192, "modality": "chat"},
            {"id": "gpt-4-turbo", "name": "GPT-4 Turbo", "contextWindow": 128000, "maxOutputTokens": 8192, "modality": "chat"},
            {"id": "o1", "name": "o1", "contextWindow": 200000, "maxOutputTokens": 100000, "modality": "chat"},
            {"id": "o3-mini", "name": "o3 mini", "contextWindow": 200000, "maxOutputTokens": 100000, "modality": "chat"},
        ],
    },
    "openai-compatible": {
        "label": "OpenAI-compatible",
        "kind": "chat",
        "models": [
            {"id": "deepseek-chat", "name": "DeepSeek Chat", "contextWindow": 64000, "maxOutputTokens": 8192, "modality": "chat"},
            {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner", "contextWindow": 64000, "maxOutputTokens": 8192, "modality": "chat"},
        ],
    },
    "anthropic": {
        "label": "Anthropic Claude",
        "kind": "chat",
        "models": [
            {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4", "contextWindow": 200000, "maxOutputTokens": 8192, "modality": "chat"},
            {"id": "claude-3-5-sonnet", "name": "Claude 3.5 Sonnet", "contextWindow": 200000, "maxOutputTokens": 8192, "modality": "chat"},
        ],
    },
    "gemini": {
        "label": "Google Gemini",
        "kind": "chat",
        "models": [
            {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "contextWindow": 1048576, "maxOutputTokens": 8192, "modality": "chat"},
            {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro", "contextWindow": 1048576, "maxOutputTokens": 8192, "modality": "chat"},
        ],
    },
    "openrouter": {
        "label": "OpenRouter",
        "kind": "chat",
        "models": [
            {"id": "deepseek/deepseek-chat", "name": "DeepSeek Chat (via OpenRouter)", "contextWindow": 64000, "maxOutputTokens": 8192, "modality": "chat"},
            {"id": "anthropic/claude-3.5-sonnet", "name": "Claude 3.5 Sonnet (via OpenRouter)", "contextWindow": 200000, "maxOutputTokens": 8192, "modality": "chat"},
        ],
    },
    "glm": {
        "label": "z.ai / GLM",
        "kind": "chat",
        "models": [
            {"id": "glm-4-plus", "name": "GLM-4 Plus", "contextWindow": 128000, "maxOutputTokens": 8192, "modality": "chat"},
        ],
    },
    "xai": {
        "label": "xAI (Grok)",
        "kind": "chat",
        "models": [
            {"id": "grok-3", "name": "Grok 3", "contextWindow": 200000, "maxOutputTokens": 8192, "modality": "chat"},
            {"id": "grok-3-mini", "name": "Grok 3 Mini", "contextWindow": 200000, "maxOutputTokens": 8192, "modality": "chat"},
        ],
    },
    "dashscope": {
        "label": "Qwen via DashScope (International)",
        "kind": "chat",
        "models": [
            {"id": "qwen-plus", "name": "Qwen Plus", "contextWindow": 131072, "maxOutputTokens": 8192, "modality": "chat"},
            {"id": "qwen-max", "name": "Qwen Max", "contextWindow": 32768, "maxOutputTokens": 8192, "modality": "chat"},
            {"id": "qwen-turbo", "name": "Qwen Turbo", "contextWindow": 131072, "maxOutputTokens": 8192, "modality": "chat"},
        ],
    },
    "dashscope-cn": {
        "label": "Qwen via DashScope (China)",
        "kind": "chat",
        "models": [
            {"id": "qwen-plus", "name": "Qwen Plus", "contextWindow": 131072, "maxOutputTokens": 8192, "modality": "chat"},
            {"id": "qwen-max", "name": "Qwen Max", "contextWindow": 32768, "maxOutputTokens": 8192, "modality": "chat"},
            {"id": "qwen-turbo", "name": "Qwen Turbo", "contextWindow": 131072, "maxOutputTokens": 8192, "modality": "chat"},
        ],
    },
    "zhipu": {
        "label": "z.ai / GLM (International)",
        "kind": "chat",
        "models": [
            {"id": "glm-4.6", "name": "GLM-4.6", "contextWindow": 200000, "maxOutputTokens": 8192, "modality": "chat"},
            {"id": "glm-4.5", "name": "GLM-4.5", "contextWindow": 128000, "maxOutputTokens": 8192, "modality": "chat"},
            {"id": "glm-4-plus", "name": "GLM-4 Plus", "contextWindow": 128000, "maxOutputTokens": 8192, "modality": "chat"},
        ],
    },
    "minimax": {
        "label": "MiniMax (Global)",
        "kind": "chat",
        "models": [
            {"id": "MiniMax-Text-01", "name": "MiniMax Text 01", "contextWindow": 1000000, "maxOutputTokens": 8192, "modality": "chat"},
            {"id": "abab6.5s-chat", "name": "abab 6.5s Chat", "contextWindow": 8192, "maxOutputTokens": 4096, "modality": "chat"},
        ],
    },
    "minimax-cn": {
        "label": "MiniMax (China)",
        "kind": "chat",
        "models": [
            {"id": "MiniMax-Text-01", "name": "MiniMax Text 01", "contextWindow": 1000000, "maxOutputTokens": 8192, "modality": "chat"},
            {"id": "abab6.5s-chat", "name": "abab 6.5s Chat", "contextWindow": 8192, "maxOutputTokens": 4096, "modality": "chat"},
        ],
    },
    "nvidia": {
        "label": "NVIDIA (NIM)",
        "kind": "chat",
        "models": [
            {"id": "deepseek-ai/deepseek-r1", "name": "DeepSeek-R1 (NVIDIA)", "contextWindow": 128000, "maxOutputTokens": 8192, "modality": "chat"},
            {"id": "meta/llama-3.3-70b-instruct", "name": "Llama 3.3 70B (NVIDIA)", "contextWindow": 128000, "maxOutputTokens": 8192, "modality": "chat"},
            {"id": "qwen/qwen2.5-72b-instruct", "name": "Qwen 2.5 72B (NVIDIA)", "contextWindow": 128000, "maxOutputTokens": 8192, "modality": "chat"},
        ],
    },
    "lmstudio": {
        "label": "LM Studio (local)",
        "kind": "chat",
        "models": [
            {"id": "local-model", "name": "Local model", "contextWindow": 32768, "maxOutputTokens": 4096, "modality": "chat"},
        ],
    },
    "local-fallback": {
        "label": "Local heuristic fallback",
        "kind": "heuristic",
        "models": [
            {"id": "local-fallback", "name": "Deterministic heuristic", "contextWindow": 0, "maxOutputTokens": 0, "modality": "heuristic"},
        ],
    },
}


def providers():
    """Sorted provider ids present in the catalog."""
    return sorted(MODEL_CATALOG.keys())


def list_models(provider=None):
    """List models; optionally filtered to one provider id.

    Returns a list of model dicts each tagged with ``provider`` and ``label``.
    A deep copy is returned so callers can never mutate the catalog.
    """
    if provider is not None:
        entry = MODEL_CATALOG.get(provider)
        if not entry:
            return []
        return [dict(m, provider=provider, label=entry["label"]) for m in deepcopy(entry.get("models") or [])]
    return [
        dict(m, provider=pid, label=entry.get("label") or pid)
        for pid, entry in MODEL_CATALOG.items()
        for m in deepcopy(entry.get("models") or [])
    ]


def model_info(provider, model_id):
    """Look up one model's metadata, or None."""
    for m in list_models(provider):
        if m.get("id") == model_id:
            return m
    return None


def supports(provider, model_id):
    """True if the provider catalog contains the model (auto-detection hint)."""
    return model_info(provider, model_id) is not None
