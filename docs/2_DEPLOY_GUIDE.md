# QuantOS AI BOAT — Deploy Guide

Ye guide batati hai ke bot ko kaise deploy (live) karna hai.
2 tarike hain: **Sandbox Preview** (testing ke liye) aur **Docker Compose** (apne PC/PC par asli deploy).

---

## Option A: Sandbox Preview (testing ke liye — ye wala abhi live hai)

Yeh Agent (AI assistant) ka testing environment hota hai. Iska maksad sirf check karna hai.

Abhi chal rahi hai:

- Preview URL: `https://5173-e0604a5f6ecf92d7.monkeycode-ai.live`
- Frontend (Vite): port `5173` — `/api` reverse-proxy karta hai backend tak
- Backend (FastAPI): port `3001`

### Chalaane ke liye (sandbox me)

```bash
# Backend
cd backend-py && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 3001

# Frontend (alag terminal)
cd frontend && npm run dev
```

### Verify

```bash
curl http://localhost:3001/api/health          # backend
curl http://localhost:5173/api/health          # frontend se proxy
```

> Sandbox temporary hai — production ke liye use mat karo.

---

## Option B: Docker Compose (apne PC par full deploy)

Ye asli deployment hai — Postgres, Redis, backend, celery worker/beat aur frontend sab Docker me.

### Prerequisites

- Docker Desktop (ya Docker Engine + Compose)
- Ollama **host machine par** installed (container ke andar nahi)
- 16GB+ RAM recommended

### Pehla dafa: keys bharo

`docker-compose.yml` ke paas (project root me) ek file banao `.env`:

```bash
cd /workspace
cp .env.production.example .env
```

Phir `.env` me ye bharo (jo use karna ho):

```bash
# --- AI Providers ---
# ChatGPT (custom slot)
USER_LLM_CUSTOM_API_KEY=sk-...
# DeepSeek via OpenRouter (key: https://openrouter.ai)
USER_LLM_OPENROUTER_API_KEY=sk-or-...
# Gemini free key
USER_LLM_GEMINI_API_KEY=AIza...
# Claude (optional)
USER_LLM_ANTHROPIC_API_KEY=sk-ant-...
# GLM (optional)
USER_LLM_GLM_API_KEY=...

# --- Database (optional, default chalta hai) ---
POSTGRES_PASSWORD=change-me
JWT_SECRET=change-me-too
```

> `docker-compose.yml` me already saare AI slots maujood hain — `.env` me sirf keys dalni hain.

### Ollama ready karo (host par)

```bash
ollama pull qwen2.5:7b
ollama serve        # agar pehle se nahi chal raha
```

### Compose up karo

```bash
docker compose up -d --build
```

### Status check

```bash
docker compose ps
docker compose logs -f backend
```

### Sab verify karo

```bash
curl http://localhost:3001/api/health
curl http://localhost:3001/api/ai/providers
curl http://localhost:3001/api/execution/status
```

Frontend browser me: `http://localhost:8080`

### Band karna

```bash
docker compose down          # sab band
docker compose down -v       # data bhi delete (careful!)
```

---

## Kaise kaam karta hai (Docker setup)

| Service | Port | Kya karta hai |
|---|---|---|
| backend | 3001 | Main FastAPI server |
| frontend | 8080 | React UI (nginx) |
| postgres | 5432 | Database (pgvector) |
| redis | 6379 | Cache / Celery broker |
| celery-worker | - | Background tasks |
| celery-beat | - | Scheduled jobs |

**Ollama connection:** backend container `host.docker.internal:11434` se Ollama tak jata hai
(host machine par Ollama chal raha hai). Linux par `extra_hosts` already configured hai
`docker-compose.yml` me.

---

## Production notes

- Asli production ke liye `docker-compose.prod.yml` aur `k8s/` folder dekho
- Production me har service ka strong password/JWT_SECRET set karo
- Secrets ko env file me rakho, code me nahi
