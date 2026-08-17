# ZZ_QuantOS AI BOAT

**Institutional AI Trading Operating System**

A full-stack, enterprise-grade AI trading operating system built batch-by-batch per the master roadmap. Combines market data, news intelligence, technical analysis, Smart Money Concepts, multi-agent AI decision making, risk management, execution (MT5), backtesting, and enterprise infrastructure into one integrated, runnable platform.

## Decision Hierarchy

Every trading decision follows this enforced pipeline:

```
News Intelligence → Official Source Check → Multi-Source Verification
→ AI Analysis (Multi-Provider · Local-First) → Historical Context
→ Market Validation (Gold · DXY · Oil · VIX · Bonds)
→ Technical Confirmation (Order Block · FVG · BOS · CHoCH · Liquidity)
→ Risk Manager (Dynamic SL/TP/Lot) → Confidence Check
→ MT5 Auto Execution → Continuous Monitoring
→ Auto Close / TP / Trailing
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (Vite + React · Port 5173 · Dashboard/Command Ctr) │
│  · /api  → reverse-proxied to backend                       │
│  · /ws   → WebSocket live streams                           │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST + WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│  Backend (Python FastAPI · Port 3001)                        │
│  Foundation: config · logging · event bus · db · security    │
│              queue · workers · scheduler · plugins · cache    │
│  Modules: market-data · news · economic · macro · historical │
│           technical · smc · ai · trading · risk · portfolio  │
│           mt5 · backtest · alerts · reports · research       │
│           features · pipeline · observability · security     │
│           admin · users · gateway · websocket · integrations │
│           multiasset · execution · mobile-ready              │
│           cloud · devops · production · validation           │
│  Persistence: JSON file store (backend-py/backend/data)      │
└──────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
cd backend-py && pip install -r requirements.txt && cd ..
npm install                     # install workspace deps (frontend)
bash start.sh                   # starts backend (3001) + frontend (5173)
```

Open http://localhost:5173 (the frontend proxies `/api` and `/ws` to the backend).

Demo login: `admin` / `admin123`, `trader` / `trader123`, `analyst` / `analyst123`.

### Manual start
```bash
cd backend-py && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 3001   # API + WebSocket on :3001
cd frontend && npm run dev     # Dashboard on :5173
```

## Batch Coverage (1–41)

| Batch | Module | Key Features |
|---|---|---|
| 01 | Foundation | Clean architecture, DDD modules, SOLID, provider framework, plugins, event bus, config, security, logging, monitoring, DB, API, WebSocket, AI gateway/registry/memory, vector DB, theme, preferences, feature flags, error handling, workers, queue, scheduler, Docker, K8s, CI/CD, tests |
| 02 | Command Center | Live dashboard, widgets, market overview, portfolio summary, AI status, news & calendar overview, alerts, notification center, workspace |
| 03 | News Terminal | 19 sources, FinBERT/FinLLM sentiment, translation, entities, keywords, fake-news & duplicate detection, cross-verification, reliability/trust/confidence scores, timeline, vector embeddings, RAG, manual source manager |
| 04 | Market Data | 12 providers, tick/OHLC/order book/trades/bid-ask/spread/volume, market sessions, historical data, live streaming, WebSocket |
| 05 | Economic Calendar | CPI/PPI/GDP/PMI/NFP/ADP/FOMC/rates/speeches (BOJ/BOE/ECB), impact tiers, historical reaction, AI impact analysis |
| 06 | Historical Intel | Historical news/market/trades, pattern matching, similar events, replay engine, market memory, AI knowledge base |
| 07 | AI Decision Center | Multi-agent (7 agents), AI consensus, decision & confidence engine, explainable AI, trade recommendation, expected pips/risk, reasoning |
| 08 | Technical Engine | Price action (HH/HL/LH/LL, swings, breakouts), 60+ candlestick patterns, 19 indicators, volume analysis, 8 timeframes (M1–W1), AI technical confirmation |
| 09 | Smart Money | Liquidity, order blocks, FVG, BOS, CHoCH, mitigation, premium/discount, kill zones, sessions, institutional volume |
| 10 | Market Validation | News × Technical × SMC × Macro × Market Data → trade validation |
| 11 | Macro Intelligence | DXY, bond yields, gold/oil/crypto correlations, global economy |
| 12 | MT5 Integration | Orders, positions, balance, equity, margin, history, manual + auto trading |
| 13–16 | Trading Core | Trading engine, order management, position monitor, SL/TP/partial/reverse, execution modes, auto-trade controller |
| 17–18 | Portfolio & Risk | Portfolio service, equity curve, capital protection, risk engine (max risk/daily loss/exposure/correlation), auto-halt |
| 19–20 | Performance & Backtest | Performance analytics, 6 strategies, equity curves, profit factor, strategy comparison |
| 21–22 | AI Learning | Outcome recording, adaptive model weights, feedback loop |
| 23 | Explainable AI | Decision explanation, contribution breakdown, timeline, transparency |
| 24 | Alerts | Email/Telegram/WhatsApp/Push/Desktop/MT5/Web, custom rules, AI recommendations |
| 25 | Reports | Daily/weekly/monthly/portfolio/risk/trade/AI reports, JSON/CSV export |
| 26 | Research Lab | Strategy builder, experiments, notebooks, sandbox, feature experiments |
| 27 | Feature Store | Versioned features, registry, online/offline, validation |
| 28 | Data Pipeline | ETL, streaming, batch, scheduling, queues, lineage |
| 29 | Observability | Health checks, metrics, logs, dashboards, alert rules |
| 30 | Security | RBAC, JWT, API keys, encryption, audit logs, rate limiting, security dashboard |
| 31 | Admin Panel | System dashboard, AI/source/provider management, roles, logs, config, jobs, health |
| 32 | Users | Auth, authorization, roles, teams, organizations, profiles, activity |
| 33 | API Gateway | Versioned REST, auth, rate limiting, analytics, docs |
| 34 | WebSocket | Live news/market/orders/portfolio/AI/presence, reconnection, broadcasting |
| 35 | Integrations | MT5, TradingView, Discord, Telegram, WhatsApp, Drive, Dropbox, Slack, webhooks |
| 36 | Mobile Ready | Responsive UI, PWA manifest, mobile dashboard |
| 37 | Multi-Asset | Forex, crypto, stocks, ETFs, futures, options, commodities, bonds, synthetic |
| 38 | Cloud Infrastructure | AWS/Azure/GCP multi-cloud, object storage, load balancers, CDN, auto-scaling, cost estimation, backup/restore lifecycle, failure simulation |
| 39 | DevOps & CI/CD | GitHub Actions / GitLab CI / Docker / K8s / Helm pipelines, async step-by-step runs, releases with semver bumping, K8s cluster + helm chart state, deployment log |
| 40 | Production Readiness | 16-item go-live checklist, async stress/load tests (p50/p95/p99), security hardening scans, performance recommendations, high-availability + failover, DR plan + drills, production audit |
| 41 | System Validation | 9 enterprise validation suites, run-all certification, full docs coverage, production certification gate |

## Core AI Trading Logic

```
Market Data + News + Economic + Historical + Technical + SMC + Macro + Risk + Portfolio
                 ↓  Multi-Agent AI Consensus  ↓
              Trade Recommendation → Confidence → Expected Pips/RR/SL/TP
                 ↓  Manual Approval OR Auto Execute (MT5)
              Live Trade Monitoring → Dynamic Re-Analysis → Hold/Modify/Partial/Close/Reverse
                 ↓  Learning Engine  ←  feedback
```

## API Highlights

| Endpoint | Description |
|---|---|
| `GET /api/health` | Health check |
| `GET /api/market/quotes` · `/market/candles/:symbol` | Live quotes & OHLC |
| `GET /api/news` · `/api/economic/calendar` | News & calendar with AI analysis |
| `GET /api/technical/multitimeframe/:symbol` | MTF technical analysis |
| `POST /api/ai/analyze/:symbol` | Full AI multi-agent decision |
| `POST /api/trading/orders` | Place order (risk-checked) |
| `POST /api/backtest/run` | Backtest any strategy |
| `GET /api/cloud/overview` | Multi-cloud cost & capacity |
| `GET /api/devops/overview` · `/devops/k8s` | CI/CD pipelines, releases, K8s |
| `GET /api/production/overview` | Go-live checklist, HA, DR, audits |
| `GET /api/validation/suites` · `POST /validation/run-all` | 9 validation suites + certification |
| `GET /api/admin/dashboard` · `/api/security/dashboard` | Admin & security |
| `WS /ws` | Subscribe to `market`, `news`, `orders`, `portfolio`, `ai`, `alerts` |

## Testing & Validation

```bash
cd backend-py && python3 -m pytest app/tests -q   # pytest unit tests across all modules
```

The built-in **Enterprise System Validation** (`/api/validation/run-all`) runs 9 suites —
market-data, AI workflow, news intelligence, technical analysis, fundamental analysis,
MT5 lifecycle, risk & portfolio, live API probes, and documentation audit — and issues a
**production certification** when all suites pass at ≥90% (see `docs/api.md` for the full
API surface).

## Docker / K8s / CI

```bash
docker compose up --build            # containerized full stack
kubectl apply -f k8s/quantos.yaml    # Kubernetes deployment
# CI: .github/workflows/ci.yml — python tests + smoke test + Docker build
```

## Project Layout

```
backend-py/app/
  foundation/        # Batch 01 infrastructure
  modules/           # Domain modules per batch
    marketdata news economic macro historical technical ai risk
    portfolio trading execution mt5 backtest alerts reports research
    features pipeline observability security admin users
    integrations multiasset websocket
    cloud devops production validation
  routes/            # API gateway routes
  main.py            # Bootstrap + wiring
frontend/src/
  pages/             # 20 dashboard pages
  components/        # charts, panels, widgets
  api.js             # REST + WebSocket client
docs/
  api.md             # Full REST API reference
  MT5_CONNECTION.md  # Connect a real MT5 account via the bridge
bridge/
  mt5_bridge.py      # REST bridge that runs next to your MT5 terminal
```

**Live market data (free, no API keys):** Quotes and candles are streamed in
real time from Binance (crypto) and Yahoo Finance (forex, gold, indices,
stocks, oil), with automatic fallback to a realistic simulator when the network
is unreachable. The Dashboard embeds a live **TradingView** advanced chart
(real-time quotes, indicators, drawing tools) for any of the 12 instruments.

**MT5:** Demo mode simulates a broker account out of the box. To trade a real
account, run `bridge/mt5_bridge.py` next to your MT5 terminal and set
`MT5_ENABLED=live` + `MT5_BRIDGE_URL` (see `docs/MT5_CONNECTION.md`). News uses
a built-in simulator provider in demo mode; premium news APIs plug into the same
provider framework via API keys in `backend-py/app/config.py`.
"# Z-Z-QuantOS-AI-BOAT-2" 
"# Z-Z-QuantOS-AI-BOAT-" 
"# Z-Z-QuantOS-AI-Forex-BOAT-2" 
"# Z-Z-QuantOS-AI-Forex-BOAT-2" 
"# Z-Z-QuantOS-AI-Forex-BOAT-1" 
"# Z-Z-QuantOS-AI-Forex-BOAT" 
"# Z-Z-QuantOS-AI-BOAT-1" 
"# Z-Z-QuantOS-AI-BOAT-3" 
"# Z-Z-QuantOS-AI-Forex-BOAT--" 
"# Z-Z-QuantOS-AI-BOAT-" 
"# ZZ_QuantOS-AI-BOAT__" 
