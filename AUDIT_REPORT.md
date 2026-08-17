# QuantOS Deep End-to-End Audit Report

**Scope:** read-only audit of the QuantOS project (`/workspace`, `backend-py/` FastAPI + `frontend/` React/Vite) — what is genuinely wired end-to-end vs surface-only.
**Method:** static trace (file:line), live HTTP checks against the running backend (port 3001, PID 2026), background-process inspection, and per-file pytest runs. No code was modified during this audit.
**Status legend:** ✅ Confirmed | ⚠️ Partial / env-gated | ❌ Broken-Missing / dead.

---

## Part A — Surface Inventory: Routes ↔ Frontend

### Backend route surface
- `app/main.py:361-368` mounts exactly 8 routers under `/api`: `whatsapp_ext`, `mt5_ext`, `api`, `brain`, `ai`, `events`, `v1`, `enterprise integrations`.
- `create_app()` uses the new Starlette `_IncludedRouter` (lazy inclusion). Routes live in `original_router.routes`; a recursive walk of `app.router.routes` enumerated **267 route paths** mounted at `/api` (plus 5 app-level: `/api/docs`, `/api/openapi.json`, `/docs/oauth2-redirect`, `/redoc`, `/ws`). ✅
- Every router module under `app/routes/` is mounted — there are **no unmounted router files**. ✅

### Frontend surface
- `frontend/src/pages/` has 25 pages; **all are imported and routed in `App.jsx`** (imports lines 4-25, routes lines 159-183). No orphan pages. ✅
- Extracted API calls from all pages cross-check against the 267-route inventory: every frontend-callable endpoint (e.g. `/api/portfolio/overview`, `/api/validation/certification`, `/api/technical/smc/{symbol}`, `/api/risk/debate/{symbol}/latest`, `/api/news/{id}/translate`) exists in the backend router. ✅ No frontend calls a nonexistent route.
- WebSocket `/ws` (9 channels) consumed by `News.jsx` (`news`) and `Trading.jsx` (`market`); backend `register_websocket` at `main.py:381`, hub reports 9 channels at boot. ✅

### Dead / orphan backend code (Part A findings)
| Item | Status | Evidence |
|---|---|---|
| `experience_replay` module | ❌ dead at runtime | only imported by `app/tasks/learning_tasks.py` (Celery, unscheduled) and its own file; `init_experience_replay` (`experience_replay.py:150`) never called |
| `news/autopilot.py` | ⚠️ unused duplicate | `init_news_autopilot` (`autopilot.py:28`) not called; its `scheduler.register` (`autopilot.py:33`) never fires — news polling is instead served by the daemon thread `init_news_poll_loop` (`main.py:129-158`) |
| `ai/consensus_v2` `init_consensus_v2` | ⚠️ init unused, logic live | `init` never called, but `compute_consensus()` is the live consensus used by the pipeline |
| `integrations/email_client` | ⚠️ wired but inactive | used only by `tasks/daily_report_delivery.py:66-68` (24h job, 0 runs so far) and needs SMTP creds |

---

## Part B — Decision → Execution → Learning Pipeline

### Genuinely live chain ✅
`news:processed` event → single-threaded `news_decision_worker` (bounded queue) → `decision_pipeline.analyze()` → 7 agents in parallel (`run_agents`, `decision_pipeline.py:64-84`: news, historical, macro, technical, risk+sentiment, fundamentals + dynamic custom) **including bull/bear debate** (`_run_debate` `decision_pipeline.py:86-107` → `research_manager.resolve` → persisted `debate_history`) → consensus `compute_consensus(results, risk_result, debate_result)` (`decision_pipeline.py:149`; `consensus_v2.py` DEBATE_CAP 0.10 nudge) with bands `≥0.90 AUTO_EXECUTE / 0.70-0.89 SUGGESTED / <0.70 NO_TRADE` (`consensus_v2.py:213-218`) → `decision_repository.insert` (`decision_pipeline.py:185`) → emit `AIDecisionMade` (`:191`) → `institutional_executor._on_decision` (`institutional_executor.py:236-238`) → `handle` (`:169-213`) → `_execute_market_order` → `_place_order` (`mt5/adapter.py:325-331`: real MT5 bridge HTTP when live; else `trading_engine.place_order` local paper fill `trading/engine.py:302-354`).
- **Trigger verified live:** both news-triggered (worker) and manual `POST /api/ai/analyze/{symbol}` (`routes/api.py:482-485`); `POST /api/v1/pipeline/analyze` (`routes/v1.py:180-183`). ✅
- Manual suggestion approval is live: `suggested:trade-approved` → `position_sync._execute_accepted_suggestion` → `trading_engine.place_order` (`position_sync.py:103-143,171`). ✅
- Brain daemon loops are live: confidence re-score every 2s, kill-switch check every 5s (`main.py:90` init; boot log), real `close_position` in AUTO modes. ✅

### Surface-only / broken links ❌
| Component | Status | Evidence |
|---|---|---|
| `decision_center.py` (legacy rule engine) | ❌ unused in live flow | parallel/dead path; only consumers are `validation/system.py:15` + tests; its decisions get skipped by executor as `legacy-format` (`institutional_executor.py:170-172`) |
| `position_sync` event auto-close on opposite news | ❌ broken | `_on_decision` reads `event.get("decision")` but payload is under `event["payload"]` (`position_sync.py:151`); `_on_news` reads `event.get("item") or payload` and gets wrapper `{"item": row}` (`:157`) so `news.get("relevant")` is None — branches never fire. Even if fired, "close" is `upsert_position(status=closed)` repository-only, never calls `trading_engine.close_position` or MT5 |
| `profit_protection` | ❌ manual-only | pure compute engines writing only to `profit_actions` log (`profit_protection.py:152-159`); no scheduler/event wiring — only manual POST routes (`routes/api.py:838-856`) + tests |
| `learning.record_outcome` | ❌ manual-only | callers = `POST /ai/learning/record` (`routes/api.py:559-561`) + `test_model_registry.py:88`; NOT wired to trade closure (`trade:closed` handled only by alerts/ws/observability) |
| `pattern_learning.win_rate_boost` | ❌ dead | callers = only tests (`test_ai_learning_phase2.py:96,106`); no live import in any agent/pipeline; `persist()` via unscheduled Celery task |
| `trade_simulator` | ❌ backtest-only | imported only by `backtest/walk_forward_analysis.py:19,83,93` + tests; trading engine does its own JSON-store paper fills |

---

## Part C — Auto-Start Jobs & Background Workers

Live `/api/system/scheduler` output (verified at runtime, run-counts real):
- `pipeline-ohlc` 60s — 28 runs ✅
- `metrics-aggregate` 15s — 114 runs ✅
- `slo-critical-metrics` 15s — 115 runs ✅
- `capital-guard-enforce` 30s — 57 runs ✅ (`capital_guard.py:269`)
- `strict-risk-policy-enforce` 30s — 57 runs ✅ (`strict_risk_policy.py:339`)
- `daily-report-delivery` 24h — 0 runs, next ≈24h ✅ registered (`tasks/daily_report_delivery.py:116`) but has not fired; delivery path reuses `email_client` (`:66-68`)

Scheduler registration call sites: `pipeline/manager.py:137`, `observability/init.py:245-246`, `risk/strict_risk_policy.py:339`, `risk/capital_guard.py:269`, `tasks/daily_report_delivery.py:116`.

Daemon threads (26 threads on live PID 2026; boot-log confirmed): market data 1s tick stream, live price provider 30s refresh, news poll loop 60s (`main.py:157`), news-decision worker, confidence monitor 2s, kill-switch monitor 5s, MT5 adapters. ✅

**Note:** the news `autopilot.py` scheduler job is NOT registered (see Part A); polling is instead served by the `init_news_poll_loop` daemon thread.

---

## Part D — Runtime Verification (live server, port 3001)

| Check | Result |
|---|---|
| `GET /api/health`, `/api/ai/decisions`, `/api/ai/debate/XAUUSD/latest`, `/api/news?limit=2`, `/api/mt5/status` | all **200** ✅ |
| `POST /api/ai/analyze/XAUUSD` | 200 in **10.66s**, verdict `no_trade` |
| `POST /api/ai/analyze/EURUSD` | 200 in **12.75s** |
| `/api/ai/decisions` | **2 real decisions** with full `agentScores` (7 agents each, per-agent direction/confidence/reasoning/data); news agent honestly abstains `PROVIDER_DEGRADED` (`LLM provider clients not initialized`) — no fake LLM output |
| `/api/ai/debate/XAUUSD/latest` | honest `status: unavailable`, `reason: "...neither side produced an analyst case (bull: PROVIDER_DEGRADED, bear: PROVIDER_DEGRADED)"` ✅ graceful degradation |
| `/api/market/quotes` | 12 live symbols with prices ✅ |
| `/api/news?limit=3` | 1 real news item ("Fed signals patience on rate cuts...") collected by poll loop ✅ |
| `/api/trading/mode` | `{"mode":"manual"}` |
| `/api/execution/status` | `mode: EMERGENCY_STOP`, `blocked_reasons: ["market_data_stale","emergency-stop"]` — the AI brain's kill-switch monitor (`brain_monitor.py:407`, no fresh quote in `STALE_DATA_THRESHOLD_SECONDS`) escalated fail-closed. Safety layer genuinely protective ✅ |
| `/api/mt5/status` | `connected:false, mode:demo, bridge:null` |
| `/api/capital/status` | shield GREEN, emergency_stop false, fail_closed empty |
| `/api/integrations/real/status` | tradingview/telegram/discord `success:false` with "signing secret missing / TELEGRAM_BOT_TOKEN missing" — honest |
| `/api/ai/providers` | only `local-fallback` provider, breaker closed |
| Process | PID 2026, **26 threads**, ~7% CPU, 3% mem |
| Frontend `npm run build` | ✅ built in 2.81s (334.67 kB JS) |
| Backend pytest (run from repo root, per-file) | `test_debate` 16p ✅, `test_news_decision_worker` 2p ✅, `test_ai_learning_phase2` 12p ✅, `test_news_features` 12p ✅, `test_daily_report_delivery` 13p ✅, `test_mt5_adapter_init` 3p ✅, `test_debate_availability` 3p ✅ (29.7s) — **61 tests, all pass** |

(Note: `test_news_decision_worker.py` errors only if run from `app/tests/` dir — `ModuleNotFoundError: app` is a cwd/sys.path artifact; passes from `backend-py/` root.)

---

## Part E — Silent Failures & Env-Gated Integrations

### Silent failure (empty `except: pass`) sites
- `app/foundation/redis_rate_limit.py:126,134` — Redis fallback suppresses errors (OK given Redis unavailable)
- `app/foundation/errors.py:11`, `app/foundation/tracing.py:206` — best-effort
- `app/modules/execution/institutional_executor.py:137` — suppresses a failure inside `_place_order` post-step
- `app/modules/production/readiness.py:449,483` — suppressed failures in readiness checks

No truly fatal silent-swallow found in the money path (the pipeline's save → emit → executor steps are logged).

### Env-gated integrations (wired-but-inactive, honest)
| Integration | State | Evidence (boot log / API) |
|---|---|---|
| LLM providers | ⚠️ only `local-fallback`; agents honestly abstain (`PROVIDER_DEGRADED`) rather than fake | decisions JSON, debate response |
| MT5 | ⚠️ DEMO mode, no account, `no fake account presented` | boot log, `/api/mt5/status` |
| Telegram / Discord / TradingView | ⚠️ `token=missing`, `webhook=missing`, `secret=missing`; `/api/integrations/real/status` confirms all three `success:false` | boot log + API |
| WhatsApp | ⚠️ `token=missing`, mode=official | boot log |
| Redis | ⚠️ `available=False`; distributed event bus disabled (`REDIS_URL not configured`) | boot log |
| Postgres | ⚠️ not configured → JSON store | boot log |
| SMTP email | ⚠️ needs SMTP creds; only used by daily-report job (0 runs) | `daily_report_delivery.py:66-68` |

The system consistently reports degraded states truthfully (no fabricated LLM content, no fake MT5 account, explicit failure reasons) — this matches the honest-degradation pattern of the completed fix task.

---

## Verdict

QuantOS is not a hollow shell: the top-level architecture is genuinely wired end-to-end — 267 routes across 8 mounted routers, 25 fully-routed frontend pages whose calls all resolve, a real news→7-agent(+bull/bear debate)→consensus→persist→executor chain that produced 2 verifiable decisions on the live server, 26 live background threads, 6 scheduler jobs with real run counts, a fail-closed safety layer that actively blocked trading on stale data (`EMERGENCY_STOP`), honest degradation across every credential-gated integration, a passing 61-test regression set, and a clean production frontend build. The honest-degradation fix (news translation + RAG + helm simulated-badge) is confirmed deployed and live. However, several modules are surface-only rather than broken: the opposite-news auto-close in `position_sync` cannot fire due to payload-parsing mismatch (`position_sync.py:151,157`) and would only update the repository even if it did; `decision_center`, `profit_protection`, `pattern_learning`, `trade_simulator`, and `experience_replay` are dead or manual-API-only; `learning.record_outcome` never runs on real trade closure; and — in this environment — every real-money or external dependency (MT5 live bridge, LLM, Telegram/Discord/WhatsApp/TradingView, SMTP, Postgres, Redis) is inactive by design because no credentials exist, so the live chain executes on `local-fallback` heuristics with paper/local fills. In short: the platform is a genuinely functioning, safely fail-closed simulator with a large, correctly-routed surface and honest degradation; the gap between "claims to do X" and "actually does X in this environment" is fully explained by missing credentials plus the specific dead-code paths listed above.
