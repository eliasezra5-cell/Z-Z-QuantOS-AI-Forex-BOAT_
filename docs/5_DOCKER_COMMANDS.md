# QuantOS AI BOAT — Docker Deploy Commands (Copy-Paste Runbook)

Ye runbook hai — **har command copy-paste karo** apne PC ke terminal me, start se end tak.
(Windows: Command Prompt/PowerShell me; Linux/Mac: terminal me)

---

## STEP 0: Kya chahiye (pehle check karo)

```bash
docker --version
docker compose version
```

- **Docker Desktop** install nahi to: https://www.docker.com/products/docker-desktop/
  (Windows/Mac) ya Linux par: `sudo apt install docker.io docker-compose-plugin`
- Docker Desktop **khula (running)** hona chahiye — "Docker Desktop is running" dikhe

---

## STEP 1: Ollama install karo (local AI)

### Windows
https://ollama.com/download se Ollama install karo (double-click, next-next).
Phir terminal me model download karo:

```bash
ollama pull qwen2.5:7b
```

### Linux/Mac
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:7b
```

### Verify Ollama chal raha hai
```bash
curl http://localhost:11434/v1/models
```
Agar kuch response aaya — OK. "connection refused" aaye to pehle:
```bash
ollama serve
```
(Windows me Ollama app background me chalta hai, `ollama serve` ki zaroorat nahi)

---

## STEP 2: Project copy karo

```bash
git clone <aapka-repo-url> quantos
cd quantos
```

---

## STEP 3: Keys ka file banao (ZAROORI — is path me required hai)

**Simple stack** (`docker-compose.prod.yml`) backend ki saari settings `.env` file se leta
hai, isliye `.env` banana **zaroori** hai. Root folder me:

```bash
cp .env.production.example .env
```

Phir `.env` edit karke ye bharo (jo use karna ho):

```bash
# Primary slot — pehle se prod stack me Ollama override hai, isliye ye chodo
# ChatGPT (custom slot)
USER_LLM_CUSTOM_BASE_URL=https://api.openai.com/v1
USER_LLM_CUSTOM_API_KEY=sk-...
USER_LLM_CUSTOM_MODEL=gpt-4o-mini
# DeepSeek via OpenRouter
USER_LLM_OPENROUTER_API_KEY=sk-or-...
# Gemini free
USER_LLM_GEMINI_API_KEY=AIza...
```

**Sabse zaroori line** — market_data_stale masla na aaye isliye:

```bash
STALE_DATA_THRESHOLD_SECONDS=45
```

(`.env.production.example` me ye 30 hai — use 45 kar do, warna purana stale masla wapas aa sakta hai)

> WARNING: `USER_LLM_CUSTOM_BASE_URL` bina valid key ke mat dalo — 401 par bot
> EMERGENCY_STOP ho jata hai.

> Ollama primary slot hai (prod compose me already override kiya hai), model download
> hone ke baad hi backend start karo — warna Ollama pehle attempt fail karega.

---

## STEP 4: Build + start karo (Docker Compose)

Project root (`quantos` folder) me — **simple prod stack** (recommended):

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Ya agar full stack chahiye (Postgres + Redis + Celery ke saath):

```bash
docker compose up -d --build
```

- **Pehli baar** 5-10 min lagega (images build hoti hain — pip install + npm build)
- Baad ki baar seconds me hoga

### Kaam kar raha hai check karo

```bash
docker compose -f docker-compose.prod.yml ps
```

Saare containers `Up` honi chahiye. Agar koi `restarting` ho to logs dekho:

```bash
docker compose -f docker-compose.prod.yml logs -f backend
```

(Ctrl+C se logs band karo)

---

## STEP 5: Verify karo — sab theek hai?

```bash
# Backend healthy?
curl http://localhost:3001/api/health

# AI providers registered (Ollama + backups)?
curl http://localhost:3001/api/ai/providers

# Execution status — "mode: DISABLED" hona chahiye, EMERGENCY_STOP NAHI
curl http://localhost:3001/api/execution/status
```

Frontend browser me kholo: **http://localhost:8080**

Ollama test (agar primary Ollama hai):

```bash
curl -X POST http://localhost:3001/api/ai/reason \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","context":"docker test"}'
```

Response me provider `openai-compatible` aana chahiye, `local-fallback` nahi.

---

## STEP 6: Keys change karni hon to (baad me)

`.env` me key badlo, phir containers restart karo (naya env lagega):

```bash
docker compose -f docker-compose.prod.yml up -d
```

Koi error aaye to container dobara banao:

```bash
docker compose -f docker-compose.prod.yml up -d --build --force-recreate
```

---

## Reddit news source enable karna

Deploy ke baad Reddit source default `disabled` hota hai. Enable karne ke 2 tarike:

### Tarika 1 — UI se (sabse aasan)

Browser me **News Terminal** kholo → **Manual Source Manager** panel →
1. Source name: `Reddit`
2. Type dropdown me **Reddit** choose karo
3. Subreddit(s): `Forex, wallstreetbets, economy`
4. **Add Source** dabao

Ye nayi Reddit source bana dega (pehle se enabled).

### Tarika 2 — API se (built-in reddit source enable)

Linux/Mac/Git Bash:

```bash
curl -X PUT http://localhost:3001/api/v1/news/sources/reddit \
  -H "Content-Type: application/json" \
  -d '{"name":"Reddit","type":"reddit","enabled":true,"config":{"subreddits":["Forex","wallstreetbets","economy"]}}'
```

Windows PowerShell (Invoke-RestMethod, quote escaping nahi chahiye):

```powershell
Invoke-RestMethod -Method Put -Uri "http://localhost:3001/api/v1/news/sources/reddit" -ContentType "application/json" -Body '{"name":"Reddit","type":"reddit","enabled":true,"config":{"subreddits":["Forex","wallstreetbets","economy"]}}'
```

### Verify + items dekhna

```bash
# Source enabled hai?
curl http://localhost:3001/api/news/sources | findstr reddit

# Sirf Reddit items dikhao (server-side filter)
curl "http://localhost:3001/api/news?limit=20&sourceType=reddit"
```

News Terminal me origin filter me **"Reddit"** choose karo — sirf Reddit posts dikhenge.
(Reddit posts apne post-timestamp ke mutabiq sort hote hain, isliye general feed ke top me purane posts nahi aate — filter use karo.)

---

## Common commands

```bash
# Status
docker compose -f docker-compose.prod.yml ps

# Saare services ke logs (live)
docker compose -f docker-compose.prod.yml logs -f

# Sirf backend ke logs
docker compose -f docker-compose.prod.yml logs -f backend

# Band karna (data safe rehta hai)
docker compose -f docker-compose.prod.yml down

# Band karna + data bhi delete (careful!)
docker compose -f docker-compose.prod.yml down -v

# Sab dobara start (band hone ke baad)
docker compose -f docker-compose.prod.yml up -d
```

---

## Important notes

1. **Ollama container ke andar nahi** — host machine par chalta hai. Backend
   `host.docker.internal:11434` se usse baat karta hai (already configured).
2. Agar Ollama port 11434 different ho (ya remote) to `docker-compose.prod.yml` me
   `USER_LLM_BASE_URL` badal sakte ho.
3. **Ports in use hain?** Backend `3001`, Frontend `8080` — agar koi aur cheez inhe
   use kar rahi ho to error aayega. Pehle band karo ya compose me port badlo.
4. Frontend `8080` par hai (dev `5173` pe nahi). Browser me `http://localhost:8080`.
5. Docker Desktop ka memory kam ho to settings me 8GB+ do (16GB RAM PC par 8GB theek hai).
