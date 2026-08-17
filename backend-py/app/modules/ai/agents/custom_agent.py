"""Custom Agent Runner.

Loads user-defined agents (``CustomAIAgent`` from the repository) into the
``asyncio.gather`` loop. Supported provider types:

  - ``free_local``     : uses the built-in local-fallback provider (no key)
  - ``paid_openai``    : OpenAI-compatible client (``USER_LLM_BASE_URL`` or OpenAI)
  - ``paid_anthropic`` : Anthropic Messages API client
  - ``paid_gemini``    : Google Gemini generateContent client
  - ``paid_deepseek``  : DeepSeek OpenAI-compatible endpoint
  - ``custom_http``    : OpenAI-compatible client pointed at ``USER_LLM_BASE_URL``

Every paid provider uses the agent's decrypted API key (stored encrypted, never
logged). When a paid provider is selected but its required config (API key /
base URL) is missing, the agent degrades to ``PROVIDER_DEGRADED`` with a clear
reason instead of silently falling back to the local heuristic.

Each custom agent's ``voting_weight`` (0-20%) is added to the directional
consensus AFTER the core 80% is computed, per the master formula:
``Final = 0.80*core + sum(custom weights)``.
"""
import os

from ....foundation.logger import logger
from ....persistence.repository import decrypt_api_key
from ..clients import (
    AnthropicClient,
    GeminiClient,
    OpenAICompatibleClient,
    LocalFallbackClient,
    ManagedProvider,
    LLMError,
    RateLimiter,
    CircuitBreaker,
)
from .base import AgentResult, clamp01

_PAID_DEFAULT_MODELS = {
    "paid_openai": "gpt-4o-mini",
    "paid_anthropic": "claude-sonnet-4-20250514",
    "paid_gemini": "gemini-2.0-flash",
    "paid_deepseek": "deepseek-chat",
    "custom_http": "deepseek-chat",
    "xai": "grok-3",
    "dashscope": "qwen-plus",
    "dashscope-cn": "qwen-plus",
    "zhipu": "glm-4.6",
    "minimax": "MiniMax-Text-01",
    "minimax-cn": "MiniMax-Text-01",
    "nvidia": "deepseek-ai/deepseek-r1",
}


class CustomAgentRunner:
    def __init__(self, agent):
        self.agent = agent
        self.id = f"custom-{agent.get('id')}"
        self.name = agent.get("name") or self.id
        self.weight = float(agent.get("voting_weight") or 0.0)
        self.provider_type = agent.get("provider_type") or "free_local"
        self.model_name = agent.get("model_name") or "default"
        self.system_prompt = agent.get("system_prompt") or ""
        self.base_url = (agent.get("base_url") or "").strip()
        self._provider = None

    def _get_provider(self):
        if self._provider is not None:
            return self._provider
        if self.provider_type == "free_local":
            client = LocalFallbackClient()
        else:
            api_key = decrypt_api_key(self.agent.get("api_key_encrypted"))
            if not api_key:
                raise LLMError(f"{self.provider_type} provider requires an API key")
            model = self.model_name
            if model in ("", "default"):
                model = _PAID_DEFAULT_MODELS.get(self.provider_type, "gpt-4o-mini")
            if self.provider_type == "paid_openai":
                base_url = self.base_url or os.environ.get("USER_LLM_BASE_URL", "") or "https://api.openai.com/v1"
                client = OpenAICompatibleClient(base_url=base_url, api_key=api_key, model=model)
            elif self.provider_type == "paid_anthropic":
                client = AnthropicClient(api_key, model=model)
            elif self.provider_type == "paid_gemini":
                client = GeminiClient(api_key, model=model)
            elif self.provider_type == "paid_deepseek":
                client = OpenAICompatibleClient(base_url=self.base_url or "https://api.deepseek.com/v1", api_key=api_key, model=model)
            elif self.provider_type == "custom_http":
                base_url = self.base_url or os.environ.get("USER_LLM_BASE_URL", "")
                if not base_url:
                    raise LLMError("custom_http provider requires a Base URL (set it in the form or USER_LLM_BASE_URL)")
                client = OpenAICompatibleClient(base_url=base_url, api_key=api_key, model=model)
            elif self.provider_type == "xai":
                client = OpenAICompatibleClient(base_url=self.base_url or "https://api.x.ai/v1", api_key=api_key, model=model)
            elif self.provider_type == "dashscope":
                client = OpenAICompatibleClient(base_url=self.base_url or "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", api_key=api_key, model=model)
            elif self.provider_type == "dashscope-cn":
                client = OpenAICompatibleClient(base_url=self.base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1", api_key=api_key, model=model)
            elif self.provider_type == "zhipu":
                client = OpenAICompatibleClient(base_url=self.base_url or "https://api.z.ai/api/paas/v4", api_key=api_key, model=model)
            elif self.provider_type == "minimax":
                client = OpenAICompatibleClient(base_url=self.base_url or "https://api.minimax.io/v1", api_key=api_key, model=model)
            elif self.provider_type == "minimax-cn":
                client = OpenAICompatibleClient(base_url=self.base_url or "https://api.minimaxi.com/v1", api_key=api_key, model=model)
            elif self.provider_type == "nvidia":
                client = OpenAICompatibleClient(base_url=self.base_url or "https://integrate.api.nvidia.com/v1", api_key=api_key, model=model)
            else:
                raise LLMError(f"unknown provider_type: {self.provider_type}")
        self._provider = ManagedProvider(client, retries=1, breaker=CircuitBreaker(failures=3),
                                         limiter=RateLimiter(rpm=20))
        return self._provider

    async def run(self, context=None):
        context = context or {}
        prompt = self.system_prompt or (
            "You are a specialized trading agent. Analyze the given gold market "
            "context and decide direction and confidence. Respond with STRICT JSON "
            '{"direction": "buy"|"sell"|"neutral", "confidence": 0.0..1.0, '
            '"reasoning": "..."}'
        )
        summary = context.get("summary") or context.get("contextSummary") or {}
        user_content = (
            f"Symbol: {context.get('symbol', 'XAUUSD')}\n"
            f"Summary: {summary}\n"
            f"News: {context.get('news') or []}\n"
            "Return strict JSON."
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content},
        ]
        try:
            provider = self._get_provider()
            result = provider.complete_custom(messages, parser=_custom_parse, temperature=0.1, max_tokens=400)
        except LLMError as exc:
            logger.warn(f"Custom agent {self.name} failed: {exc}")
            return AgentResult(self.id, self.name, self.weight, abstention="PROVIDER_DEGRADED",
                               reasoning=f"Custom agent provider failure: {exc}", data={})
        direction = result["direction"]
        abstention = "TRADE"
        if direction not in ("buy", "sell"):
            abstention = "ABSTAIN" if direction == "neutral" else "DATA_INSUFFICIENT"
        return AgentResult(
            self.id, self.name, self.weight,
            direction=direction,
            confidence=clamp01(result["confidence"]),
            reasoning=result.get("reasoning", ""),
            abstention=abstention,
            data={"providerType": self.provider_type, "model": self.model_name},
        )


def _custom_parse(text, provider_id):
    import json
    import re

    text = (text or "").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise LLMError(f"{provider_id}: no JSON returned")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LLMError(f"{provider_id}: invalid JSON: {exc}") from exc
    direction = str(data.get("direction", "neutral")).lower()
    if direction not in ("buy", "sell", "neutral"):
        direction = "neutral"
    return {
        "direction": direction,
        "confidence": clamp01(data.get("confidence", 0.5)),
        "reasoning": str(data.get("reasoning", "")),
    }
