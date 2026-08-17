# QuantOS AI BOAT — Agent Install Guide (A to Z)

Ye guide batati hai ke **agent (bot)** ko naye PC par sifar se kaise install karna hai.
Har step ko step-by-step likha hai — pehli baar karne wala bhi follow kar sakta hai.

---

## Step 1: Requirements (jo cheezein pehle se chahiye)

| Cheez | Version | Kahan se |
|---|---|---|
| Python | 3.11+ | https://www.python.org/downloads/ |
| Node.js + npm | 18+ | https://nodejs.org |
| Git | latest | https://git-scm.com |
| Docker + Docker Compose | latest | https://www.docker.com/products/docker-desktop/ |
| Ollama | latest | https://ollama.com/download |

Check karne ke liye (terminal/CMD me):

```bash
python3 --version
node --version
npm --version
git --version
docker --version
docker compose version
```

---

## Step 2: Project copy karo (clone)

```bash
git clone <aapka-repo-url> quantos
cd quantos
```

---

## Step 3: Backend dependencies install karo

```bash
cd backend-py
python3 -m venv venv
source venv/bin/activate        # Windows par: venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
cd ..
```

---

## Step 4: Frontend dependencies install karo

```bash
npm install
```

(Ye root folder me chalao — project workspaces use karta hai, frontend khud install ho jayega)

---

## Step 5: Config file (.env) banao

Pehle `.env.example` copy karo:

```bash
cp backend-py/.env.example backend-py/.env
```

Phir `.env` file kholo (`backend-py/.env`) aur ye sections bharo:

1. **DeepSeek API key** (line: `USER_LLM_API_KEY=`) — https://platform.deepseek.com se lo
2. **Gemini API key** (line: `USER_LLM_GEMINI_API_KEY=`) — https://aistudio.google.com se lo (free)
3. ChatGPT key (agar chahiye) — `USER_LLM_CUSTOM_BASE_URL=https://api.openai.com/v1` aur `USER_LLM_CUSTOM_API_KEY=sk-...`

> WARNING: `USER_LLM_CUSTOM_BASE_URL` bina valid key ke mat bharo — 401 error par bot
> EMERGENCY_STOP mode me chala jata hai. Base URL aur key hamesha ek saath bharo.

4. Local AI ke liye (Ollama) — `USER_LLM_BASE_URL=http://localhost:11434/v1`, `USER_LLM_API_KEY=` (khali), `USER_LLM_MODEL=qwen2.5:7b`

---

## Step 6: Ollama install karo (local AI model)

Ollama install hone ke baad model download karo:

```bash
ollama pull qwen2.5:7b
```

Test karo ke Ollama chal raha hai:

```bash
curl http://localhost:11434/v1/models
```

---

## Step 7: Bot chalao

Sandbox/development mode me (backend + frontend dono ek saath):

```bash
bash start.sh
```

Ya alag alag:

```bash
# Terminal 1 — backend (port 3001)
cd backend-py && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 3001

# Terminal 2 — frontend (port 5173)
cd frontend && npm run dev
```

---

## Step 8: Verify karo ke sab theek hai

```bash
# Backend healthy hai?
curl http://localhost:3001/api/health

# Kaun se AI providers available hain?
curl http://localhost:3001/api/ai/providers

# Execution status kya hai? (mode DISABLED hona chahiye, EMERGENCY_STOP NAHI)
curl http://localhost:3001/api/execution/status
```

Frontend browser me kholo: `http://localhost:5173`

---

## Important notes

- **Keys ke bina bhi bot chalega** — sirf `local-fallback` (heuristic) use hota hai.
- Asli AI ke liye kam se kam ek real key chahiye.
- `.env` me keys change karne ke baad **server restart** zaroori hai.
- Docker me deploy karna hai to `docs/2_DEPLOY_GUIDE.md` dekho.
