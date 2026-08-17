# QuantOS AI BOAT — AI Providers Guide (Keys & Slots)

Ye guide batati hai ke kaunse AI provider add kar sakte ho, unka slot kya hai,
aur key kahan dalni hai.

---

## Failover Chain (order)

Bot ke saare agents ek hi failover chain use karte hain — pehla provider fail ho to
agli try hoti hai, aur sab fail ho jayein to `local-fallback` (heuristic, bina key ke).

Default order (real keys ke saath):

```
openai-compatible (primary) → anthropic (Claude) → gemini → openrouter → glm
→ custom-http → local-fallback (last)
```

---

## Saare slots (ek nazar)

| Slot | Env vars | Kya hai | Key zaroori? |
|---|---|---|---|
| **openai-compatible** (primary) | `USER_LLM_BASE_URL`, `USER_LLM_API_KEY`, `USER_LLM_MODEL` | DeepSeek / OpenAI / Ollama / koi bhi OpenAI-compatible | koi bhi ho sakta hai |
| **custom-http** | `USER_LLM_CUSTOM_BASE_URL`, `USER_LLM_CUSTOM_API_KEY`, `USER_LLM_CUSTOM_MODEL` | ChatGPT (OpenAI) ya koi bhi dusra OpenAI-compatible endpoint | haan (base URL + key ek saath) |
| **anthropic** | `USER_LLM_ANTHROPIC_API_KEY`, `USER_LLM_ANTHROPIC_MODEL` | Claude | haan |
| **gemini** | `USER_LLM_GEMINI_API_KEY`, `USER_LLM_GEMINI_MODEL` | Google Gemini (free tier hai) | haan |
| **openrouter** | `USER_LLM_OPENROUTER_API_KEY`, `USER_LLM_OPENROUTER_MODEL` | Multi-model aggregator — DeepSeek/GPT sab iske through | haan |
| **glm** | `USER_LLM_GLM_API_KEY`, `USER_LLM_GLM_MODEL` | Zhipu GLM | haan |
| **lmstudio** | `USER_LLM_LMSTUDIO_BASE_URL`, `USER_LLM_LMSTUDIO_MODEL` | LM Studio / local OpenAI-compatible server | nahi (bina key) |
| **azure** | `USER_LLM_AZURE_*` | Azure OpenAI (endpoint + deployment) | haan (key + endpoint) |
| **huggingface** | `USER_LLM_HUGGINGFACE_*` | Hugging Face | key ya URL |
| **local-fallback** | koi nahi | Built-in heuristic — hamesha aakhri | nahi (hamesha available) |

> **Important:** sirf `USER_LLM_BASE_URL`, `anthropic` aur `gemini` core slots hain.
> Baaki (openrouter, glm, custom-http, lmstudio, azure, huggingface) extension slots hain —
> inhe agents ke chain me **pehle hi merge kar diya gaya hai** (`provider_extensions.py` me fix).
> Ab ye sab agents ke failover me use hote hain.

---

## Aapke setup ke liye recommended combo

### Sandbox me (testing)

- **Primary:** DeepSeek — `USER_LLM_BASE_URL=https://api.deepseek.com/v1`, `USER_LLM_API_KEY=<tumhari key>`, `USER_LLM_MODEL=deepseek-chat`
- **Backup 1:** Gemini free — `USER_LLM_GEMINI_API_KEY=<free key>`
- **Backup 2 (optional):** ChatGPT — `USER_LLM_CUSTOM_BASE_URL=https://api.openai.com/v1`, `USER_LLM_CUSTOM_API_KEY=sk-...`

### Apne PC par (Docker + Ollama)

- **Primary:** Ollama local — `USER_LLM_BASE_URL=http://host.docker.internal:11434/v1`, `USER_LLM_API_KEY=` (khali), `USER_LLM_MODEL=qwen2.5:7b`
- **ChatGPT:** `USER_LLM_CUSTOM_API_KEY=sk-...`
- **DeepSeek:** `USER_LLM_OPENROUTER_API_KEY=sk-or-...` (openrouter model: `deepseek/deepseek-chat`)
- **Backup:** `USER_LLM_GEMINI_API_KEY=<free key>`

---

## Keys kahan se milegi

| Provider | URL | Note |
|---|---|---|
| DeepSeek | https://platform.deepseek.com | cheap |
| ChatGPT (OpenAI) | https://platform.openai.com/api-keys | paid |
| Gemini | https://aistudio.google.com | **free** |
| Claude | https://console.anthropic.com | paid |
| OpenRouter | https://openrouter.ai | ek key se sab models (DeepSeek, GPT, etc.) |
| GLM | https://open.bigmodel.cn | free tier hai |
| **NVIDIA NIM** | https://build.nvidia.com | **free tier** (DeepSeek-R1, Llama, Qwen) |
| **xAI (Grok)** | https://console.x.ai | paid |
| **Qwen (DashScope)** | https://dashscope.aliyun.com | free tier hai |
| **z.ai / GLM** | https://z.ai | free tier hai |
| **MiniMax** | https://platform.minimaxi.com | free tier hai |

## Batch 02 providers (additive slots)

`AI Agents Management` aur env dono se use ho sakte hain. Env ke liye `.env` me:

```
USER_LLM_NVIDIA_API_KEY=...
USER_LLM_NVIDIA_MODEL=deepseek-ai/deepseek-r1
USER_LLM_XAI_API_KEY=...
USER_LLM_DASHSCOPE_API_KEY=...
USER_LLM_ZHIPU_API_KEY=...
USER_LLM_MINIMAX_API_KEY=...
```

Key daalne ke baad server restart karo. Agent form me provider select karke
model name + key dene se "Add Custom Agent" ke through bhi connect hota hai
(Connected AI Models panel me badge "Connected" dikhta hai).

---

## Zaroori warnings

1. **`USER_LLM_CUSTOM_BASE_URL` bina valid key ke mat dalo.** Base URL set hone par slot
   register ho jata hai, aur 401 error `ai_provider_failure` kill switch latch karta hai
   → bot `EMERGENCY_STOP` mode me chala jata hai. Base URL + key hamesha ek saath dalo.
2. **Key badalne ke baad server restart karo** — `.env` boot par read hota hai.
3. **ChatGPT free version ka koi API nahi hai.** Sirf paid (platform) key chalegi, ya
   Gemini free use karo.
4. **Ek hi time par ek primary slot hota hai** (`USER_LLM_BASE_URL`). Dusre providers
   backup slots hain.
5. Koi bhi provider 5 baar fail ho to circuit breaker khul jata hai (bot us provider ko
   temporarily skip karta hai).
