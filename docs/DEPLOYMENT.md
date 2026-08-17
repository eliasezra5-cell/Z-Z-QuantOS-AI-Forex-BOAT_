# ZZ_QuantOS AI BOAT — GO LIVE RUNBOOK

This is the step-by-step guide to take the platform live with Docker on a VPS.
Follow the sections in order. Every command is copy-paste ready.

```
  INTERNET / YOUR DOMAIN
          │
          │ :443 / :80
   ┌──────▼──────┐        ┌──────────────────┐
   │   VPS host  │        │  MT5 machine     │
   │             │        │  (Windows VPS/PC)│
   │  frontend   │  /api  │                  │
   │  nginx :80 ─┼───────▶│  mt5_bridge.py   │
   │  (8080)     │        │  :5001           │
   │       │     │        │   │              │
   │  backend    │        │   ▼              │
   │  uvicorn    │        │  MT5 terminal    │
   │  :3001      │        │      │           │
   └─────────────┘        │      ▼           │
                          │    Broker        │
                          └──────────────────┘
```

---

## 1. Pre-requisites

- A **Linux VPS** (Ubuntu 22.04+ / Debian 12 recommended), at least **2 vCPU / 4 GB RAM**.
- **Docker Engine + Compose plugin** installed (below).
- A domain name (optional but recommended) pointing to the VPS IP.
- (Later) A **Windows VPS/PC with MetaTrader 5** for live trading.

### Install Docker on the VPS

```bash
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
# log out and back in so the docker group applies
docker --version && docker compose version
```

---

## 2. Get the code

```bash
git clone https://github.com/zuhairzia298-web/Z-Z-QuantOS-AI-BOAT-1.git quantos
cd quantos
git checkout 260808-feat-trading-integration-and-fixes   # latest feature branch
```

---

## 3. Environment configuration (the RULES)

```bash
cp .env.production.example .env
nano .env     # or any editor
```

**Mandatory edits:**

| Rule | What to set |
|------|-------------|
| `JWT_SECRET` | Generate a strong random value: `openssl rand -hex 32` and paste it. Never leave the default. |
| `USER_LLM_API_KEY` | Your own AI provider key (DeepSeek/OpenAI/etc). Platform keys are never used. |
| `MT5_*` | Leave `MT5_ENABLED=demo` until step 6. Then set `live` + bridge URL. |
| `POSTGRES_ENABLED` / `CELERY_ENABLED` | Keep `false` (verified JSON-store setup). |

Security rules:
- **Never commit `.env`** — it is already git-ignored (add it if missing).
- **Never paste API keys / passwords into chat, logs, or commits.**
- Keep the `.env` file readable only by root: `chmod 600 .env`.

### 3.1 Daily report delivery + optional integrations (checklist)

These enable **Feature 3/4** (slippage tracking + daily report delivery over
email / WhatsApp / Telegram). Every channel is **independently toggled and
fails safe** — leave a channel's credentials empty and it is skipped silently
(recorded `"pending"` in `integration_outbox`). No extra process is required:
the delivery job is registered on the in-process scheduler at boot.

| Variable | Expected value | Required? |
|----------|----------------|-----------|
| `REDDIT_CLIENT_ID` | Reddit app client id (for PRAW news path) | Optional — without it the collector uses the public RSS feed (automatic fallback) |
| `REDDIT_CLIENT_SECRET` | Reddit app secret (paired with the id above) | Optional |
| `SMTP_HOST` | e.g. `smtp.gmail.com` / your provider's SMTP host | For email delivery |
| `SMTP_PORT` | `587` (STARTTLS) or `465` (SSL) | For email delivery |
| `SMTP_USER` | SMTP login user | For email delivery |
| `SMTP_PASSWORD` | SMTP login password / app password | For email delivery |
| `SMTP_STARTTLS` | `true`/`false` | For email delivery |
| `EMAIL_FROM` | Sender address, e.g. `quantos@yourdomain.com` | For email delivery |
| `EMAIL_TO` | Recipient address(es), comma-separated ok | For email delivery |
| `EMAIL_SUBJECT_PREFIX` | e.g. `QuantOS AI` | Optional (defaults set) |
| `WHATSAPP_TOKEN` | Meta Graph API long-lived token | For WhatsApp delivery |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta phone-number id | For WhatsApp delivery |
| `WHATSAPP_ADMIN_NUMBER` | E.164 admin phone, e.g. `+12125550000` | For WhatsApp delivery |
| `WHATSAPP_WEBHOOK_SECRET` | Webhook verify secret | Optional (webhook only) |
| `TELEGRAM_BOT_TOKEN` | Token from BotFather | For Telegram delivery |
| `TELEGRAM_CHAT_ID` | Your chat id (or `@channel`) | For Telegram delivery |
| `REPORT_DELIVERY_INTERVAL_SECONDS` | `86400` (default, 24h) | Optional |
| `REPORT_DELIVERY_EMAIL_ENABLED` | `true`/`false` | Optional (default `true`) |
| `REPORT_DELIVERY_WHATSAPP_ENABLED` | `true`/`false` | Optional (default `true`) |
| `REPORT_DELIVERY_TELEGRAM_ENABLED` | `true`/`false` | Optional (default `true`) |

All of the above are already documented (with comments) in
`.env.production.example` — copy that file and fill what you need.

---

## 3a. Scheduler & Celery — what actually triggers the features

**Simple production stack (default, recommended):**
- The in-process scheduler (`threading.Timer`, no broker) runs
  `daily-report-delivery` automatically when the backend boots
  (registered in `app/main.py`). News polling runs on its own background
  loop. **Nothing extra to start** — `docker-compose.prod.yml` is enough.
- Keep `CELERY_ENABLED=false` (the verified JSON-store setup).

**Institutional / scaled stack (`docker-compose.yml`):**
- Adds Postgres/pgvector + Redis + `celery-worker` and `celery-beat`
  services (both already defined in the compose file — nothing to add).
- Set `CELERY_ENABLED=true`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`,
  `REDIS_URL`, and `DATABASE_URL`. The beat schedule includes
  `run-daily-report-delivery`, `run-daily-learning`, `run-daily-mistake-analysis`,
  and `poll-real-news`.
- `docker compose up` starts worker + beat automatically; manual start is
  only needed if running Celery outside compose:
  ```bash
  celery -A app.tasks.celery_app worker -l info
  celery -A app.tasks.celery_app beat  -l info
  ```

---

## 4. Build & start

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

This starts:
- `quantos-backend` — FastAPI + Uvicorn on `:3001` (JSON file store, non-root user `10001`).
- `quantos-frontend` — Nginx serving the built React app on `:80` (published on host `:8080`),
  reverse-proxying `/api` and `/ws` to the backend container.

Check status:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f backend
```

**Two deploy options — pick one:**

| Deploy | Compose file | What runs | When to use |
|--------|--------------|-----------|-------------|
| **Simple (recommended)** | `docker compose -f docker-compose.prod.yml up -d --build` | backend + frontend; delivery runs on the in-process scheduler — nothing extra | Single-node live, JSON store, no broker |
| **Institutional / scaled** | `docker compose up -d --build` | backend + frontend + postgres + redis + `celery-worker` + `celery-beat` | Postgres/pgvector + Redis + Celery needed |

The institutional compose already defines `celery-worker` and `celery-beat`,
so `docker compose up` starts everything — including the daily report beat
entry — with no manual commands.

---

## 5. Verify it is live (checklist)

Run these from the VPS:

```bash
curl -sf http://localhost:3001/api/health                       # backend up
curl -sf http://localhost:8080/ | grep -o '<title>[^<]*'         # frontend served
curl -sf http://localhost:8080/api/mt5/status                   # proxy works
curl -sf http://localhost:8080/api/capital/status               # capital guard state
```

Then open **http://YOUR_SERVER_IP:8080** in a browser and confirm:
- Dashboard loads (no console/network errors).
- `Trading Engine & MT5 Integration` shows MT5 `demo` mode.
- `Trading Control`, `AI Agents`, `Technical` (Proposed Execution Zone) pages render.
- `Recent Orders` shows filled/rejected orders with the reject **Reason** column.

### Optional: put it behind HTTPS

Simplest option — reverse proxy on the VPS with Caddy (auto TLS):

```bash
sudo apt-get install -y caddy
sudo tee /etc/caddy/Caddyfile >/dev/null <<'EOF'
trading.yourdomain.com {
    reverse_proxy 127.0.0.1:8080
}
EOF
sudo systemctl reload caddy
```

Then you only need port `80/443` open; do **not** expose `3001` publicly.

---

## 6. Connect the real MT5 bridge

Run the bridge on a **Windows machine where MetaTrader 5 is installed and logged in**
(see `docs/MT5_CONNECTION.md` for full details):

```bash
# on the MT5 machine (cmd)
pip install MetaTrader5
set MT5_LOGIN=12345678
set MT5_PASSWORD=YourPassword
set MT5_SERVER=YourBroker-Server
set BRIDGE_PORT=5001
python bridge/mt5_bridge.py
```

Open firewall port `5001` on that machine. Verify:

```bash
curl http://<MT5-MACHINE-IP>:5001/status
curl "http://<MT5-MACHINE-IP>:5001/quotes?symbols=XAUUSD,EURUSD"
```

Then on the VPS `.env`:

```env
MT5_ENABLED=live
MT5_BRIDGE_URL=http://<MT5-MACHINE-IP>:5001
```

Restart:

```bash
docker compose -f docker-compose.prod.yml up -d
```

The UI `Trading Engine` page should show `Connected`.

---

## 7. Firewall & port rules

| Port | Direction | Purpose |
|------|-----------|---------|
| `80` / `443` | public | HTTPS frontend (via Caddy/nginx) |
| `8080` | public (temporary) | direct frontend access while no TLS |
| `3001` | **never public** | backend API — only reachable inside the VPS / compose network |
| `5001` | on MT5 machine | bridge HTTP — restrict to the VPS IP |

Example (UFW):

```bash
sudo ufw allow 80,443/tcp
sudo ufw allow 8080/tcp
sudo ufw default deny incoming
sudo ufw enable
```

---

## 8. Operations

### Logs
```bash
docker compose -f docker-compose.prod.yml logs -f --tail=200 backend
```

### Backups
The only state is the JSON store + AI memory:

```bash
# stop-free backup (files are small JSON; rsync while running is fine)
tar czf /var/backups/quantos-data-$(date +%F).tgz backend-py/backend/data
```

### Updating
```bash
git pull --ff-only
docker compose -f docker-compose.prod.yml up -d --build
```

### Fail-closed behaviour (important)
- A stale market-data window or MT5 disconnect **raises a fail-closed flag** that
  blocks orders. It now **auto-clears within ~30s** once data is fresh again
  (`sync_fail_closed`). See `Recent Orders` → Reason column for the exact cause.
- `daily-lock` auto-unlocks at the next UTC day. `emergency-stop` requires a
  manual admin clear.

---

## 9. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Permission denied` writing data | `sudo chown -R 10001:10001 backend-py/backend/data` on the VPS |
| Frontend `npm ci` fails in build | Ensure root `package-lock.json` is committed/updated (`npm install`) |
| Bridge shows `connected:false` | Keep the MT5 terminal open + logged in on the bridge machine |
| Orders rejected `fail-closed: market-data-stale` | Wait ~30s for auto-recovery, or clear via capital-protection API |
| `symbol not found on account` | Set `MT5_SYMBOL_MAP` on the bridge for your broker's symbols |
| Frontend can't reach backend | Confirm `nginx.compose.conf` `proxy_pass http://backend:3001` and both services are up |

---

## 10. Recommended go-live sequence (prompts)

1. `cp .env.production.example .env && nano .env` → set `JWT_SECRET`, AI keys.
2. `docker compose -f docker-compose.prod.yml up -d --build`
3. Run the step-5 verification checklist.
4. Add HTTPS (Caddy) and lock down the firewall.
5. Deploy the MT5 bridge on the Windows machine, set `MT5_ENABLED=live`.
6. Start with `TRADING_MODE=analysis`, then `SEMI_AUTO`, and only then an AUTO mode.
