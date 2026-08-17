# QuantOS AI BOAT — Checking & Troubleshooting Guide

Ye guide batati hai ke bot kaise check karna hai, aur agar koi masla aaye to kya karna hai.

---

## Basic status checks

```bash
# 1. Backend healthy?
curl http://localhost:3001/api/health

# 2. Kaunse AI providers registered hain?
curl http://localhost:3001/api/ai/providers

# 3. Execution status — mode kya hai?
curl http://localhost:3001/api/execution/status

# 4. Brain / market data feed status
curl http://localhost:3001/api/brain/status
```

Healthy state me:

```json
{ "mode": "DISABLED", "blocked_reasons": ["auto-trading-disabled"], "emergency_stop": false }
```

---

## `mode: EMERGENCY_STOP` aaya to kya karna hai

`EMERGENCY_STOP` ka matlab bot ne trading band kar di hai. Common reasons:

| Reason (`blocked_reasons`) | Matlab | Fix |
|---|---|---|
| `market_data_stale` | Live price data "purana" laga | 45s threshold already set hai (`STALE_DATA_THRESHOLD_SECONDS=45` in `.env`). Server restart kar ke check karo. |
| `ai_provider_failure` | Kisi AI provider ne 401/5xx diya | Provider key check karo. Base URL bina valid key ke set mat rakho. |
| `emergency-stop` | Emergency latched hai | Kill switch clear karo (neeche). |

### Kill switches clear karna

```bash
curl -X POST http://localhost:3001/api/execution/kill-switches/clear \
  -H "Content-Type: application/json" \
  -d '{"actor":"admin"}'
```

Response:

```json
{ "status": "ok", "cleared": ["market_data_stale"], "mode": "DISABLED" }
```

> Latched kill switch **server restart ke baad bhi persist** hota hai (JSON store me).
> Restart ke baad ek baar clear karna zaroori hai.

---

## `ai_provider_failure` (EMERGENCY_STOP)

Ye tab aata hai jab koi AI provider call fail karta hai (401 = wrong key, 429 = rate limit, 5xx).

### Fix

1. Provider key `backend-py/.env` me check karo (correct provider ki key daali hai?)
2. Agar `USER_LLM_CUSTOM_BASE_URL` set hai to **key bhi set honi chahiye** — warna 401 aayega
3. Provider fail hone ke baad kill switch clear karo:
   ```bash
   curl -X POST http://localhost:3001/api/execution/kill-switches/clear -H "Content-Type: application/json" -d '{"actor":"admin"}'
   ```

---

## `market_data_stale` baar baar aata hai

### Reason

Live price feed ~32 second me refresh hota hai, lekin pehle threshold 30s thi — isliye
bot ko data "purana" lagta tha. Ye fix ho chuka hai:

- `.env` me `STALE_DATA_THRESHOLD_SECONDS=45` (30s ke bajaye)
- Server restart ke baad hi naya threshold active hota hai

### Check feed chala raha hai

```bash
curl http://localhost:3001/api/brain/status
```

Feed threads running dikhne chahiye (Binance + Yahoo + simulator).

---

## `local-fallback` use ho raha hai (AI real provider se nahi aa raha)

Matlab koi bhi real key configure nahi hai (ya sab fail rahe hain). Iska matlab bot
heuristic response de raha hai.

### Fix

1. `backend-py/.env` me kam se kam ek real key daalo (Gemini free sabse aasan hai)
2. Server restart karo
3. Check karo:
   ```bash
   curl http://localhost:3001/api/ai/providers
   ```
4. Test:
   ```bash
   curl -X POST http://localhost:3001/api/ai/reason \
     -H "Content-Type: application/json" \
     -d '{"symbol":"BTCUSDT","context":"test"}'
   ```

Response me provider id check karo — `local-fallback` nahi hona chahiye.

---

## Server restart karna (sandbox)

```bash
# Backend
cd backend-py && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 3001

# Frontend
cd frontend && npm run dev
```

Restart ke baad:

1. `curl http://localhost:3001/api/health` — healthy
2. Kill switches clear karo (agar EMERGENCY_STOP ho)
3. `curl http://localhost:3001/api/execution/status` — mode DISABLED
4. `curl http://localhost:3001/api/ai/providers` — real providers registered

---

## Ports summary

| Port | Kya |
|---|---|
| 3001 | Backend API |
| 5173 | Frontend (dev) |
| 8080 | Frontend (Docker/nginx) |
| 5432 | Postgres |
| 6379 | Redis |
| 11434 | Ollama (host par) |
