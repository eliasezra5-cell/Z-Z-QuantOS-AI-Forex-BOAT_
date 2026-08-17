# ZZ_QuantOS AI BOAT - API Reference

Base URL: `http://localhost:3001/api` (dev) - all endpoints return JSON.

## System & Observability

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| GET | `/health` | Service health, uptime, module states |
| GET | `/system/overview` | Health + cloud, devops, production, validation summaries |
| GET | `/system/security` | Security posture (auth, rate limit, failed logins) |
| GET | `/alerts` | Active alerts with severity |
| GET | `/features` | Feature flag states |

## Market Data

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| GET | `/market/instruments` | Instrument catalog with pip sizes |
| GET | `/market/quotes` | Live simulated quotes |
| GET | `/market/candles/:symbol/:timeframe/:count` | OHLC candles |
| GET | `/market/orderbook/:symbol` | Order book snapshot |

## News Intelligence (decision source #1)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| GET | `/news` | Ingested news with sentiment + trust scores |
| GET | `/news/sources` | Managed news source list |
| POST | `/news/sources` | Add a news source |
| POST | `/news/analyze` | Trigger AI news analysis |
| POST | `/news/analyze/realtime` | Trigger real-time news re-analysis |
| GET | `/news/sentiment` | Market-wide news sentiment snapshot |
| POST | `/news/reanalyze` | Dynamic AI re-analysis of latest headlines |

## Economic & Macro (decision source #2)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| GET | `/economic/calendar` | Economic events calendar |
| GET | `/economic/indicators` | Key economic indicators |
| GET | `/macro/overview` | Macro risk-on/risk-off snapshot |

## AI Analysis & Decision (decision sources #3-#5)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| POST | `/ai/analyze` | Full decision: 7-agent consensus, XAI, confidence |
| GET | `/ai/decisions` | Decision history |
| GET | `/ai/memory` | AI memory + vector store state |
| GET | `/ai/learning` | Learning engine weights + performance |
| GET | `/ai/agents` | Agent registry & provider configuration |
| POST | `/ai/agents` | Configure AI provider (free/paid, local first) |
| GET | `/ai/providers` | Available providers (DeepSeek, Qwen, FinGPT, etc.) |

## Technical & Fundamental Analysis (decision sources #6-#7)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| GET | `/technical/multitimeframe/:symbol` | Indicators across M1-MN1 |
| GET | `/technical/smc/:symbol` | Order blocks, FVG, BOS, CHoCH, liquidity |
| GET | `/technical/session/:symbol/:timeframe` | Session / kill-zone analysis |
| GET | `/technical/priceaction/:symbol/:timeframe` | Price action structure & levels |
| GET | `/fundamental/overview/:symbol` | Fundamentals + news sentiment fusion |

## Risk & Portfolio Management

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| GET | `/risk/settings` | Risk rules & live enforcement flags |
| PUT | `/risk/settings/:id` | Update a risk rule |
| GET | `/risk/state` | Live risk assessment state |
| GET | `/portfolio/overview` | Equity, exposure, margin, capital protection |
| GET | `/portfolio/equity-curve` | Historical equity curve |
| GET | `/portfolio/daily-summary` | Daily PnL summaries |

## Trading & Execution (MT5)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| POST | `/trading/order` | Place market order (manual/auto) |
| GET | `/trading/orders` | Order history |
| GET | `/trading/positions` | Open positions |
| POST | `/trading/positions/:id/close` | Close a position |
| POST | `/trading/positions/:id/modify` | Modify SL/TP |
| POST | `/trading/positions/:id/partial` | Partial close |
| POST | `/trading/positions/:id/reverse` | Reverse a position |
| GET | `/trading/mode` | Trading mode (manual/auto) |
| POST | `/trading/mode` | Set trading mode |
| GET | `/mt5/status` | MT5 connectivity status |
| GET | `/mt5/positions` | MT5 position feed |
| GET | `/mt5/deals` | MT5 deal history |

## Backtesting

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| POST | `/backtest` | Run a backtest for a strategy |
| GET | `/backtest/compare` | Compare all strategies |

## Cloud Infrastructure (Batch 38)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| GET | `/cloud/overview` | Providers, costs, instances, backups summary |
| GET | `/cloud/providers/:id` | Provider detail with cost breakdown |
| GET | `/cloud/providers/:id/buckets` | Object storage buckets |
| GET | `/cloud/providers/:id/load-balancers` | Load balancer fleet |
| GET | `/cloud/providers/:id/cdn` | CDN edge/hit-rate/bandwidth |
| POST | `/cloud/providers/:id/scale` | Scale instances |
| POST | `/cloud/providers/:id/autoscaling` | Set auto-scaling policy |
| POST | `/cloud/providers/:id/failover` | Simulate failure/recovery |
| GET | `/cloud/backups` | List backups |
| POST | `/cloud/backups` | Create a backup |
| POST | `/cloud/backups/:id/restore` | Restore a backup |
| GET | `/cloud/restores` | List restore jobs |

## DevOps & CI/CD (Batch 39)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| GET | `/devops/overview` | Pipelines, runs, releases, deployments |
| GET | `/devops/pipelines` | CI pipeline list |
| POST | `/devops/pipelines/:id/run` | Trigger a pipeline run |
| POST | `/devops/pipelines/:id/toggle` | Enable/disable a pipeline |
| POST | `/devops/releases` | Create a release (semver bump) |
| GET | `/devops/releases` | Release history |
| GET | `/devops/k8s` | Kubernetes cluster & helm state |
| GET | `/devops/runs/:id` | Pipeline run status/steps |
| GET | `/devops/deployments` | Deployment log |

## Production Readiness (Batch 40)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| GET | `/production/overview` | Checklist, HA, DR, audit state |
| GET | `/production/checklist` | 16-item go-live checklist |
| POST | `/production/checklist/:id` | Toggle checklist item |
| POST | `/production/stress-test` | Run async stress test |
| POST | `/production/load-test` | Run async load test |
| GET | `/production/tests` | Recent stress/load test results |
| POST | `/production/security-scan` | Run security hardening scan |
| GET | `/production/security-scans` | Scan history |
| GET | `/production/performance` | Performance recommendations |
| POST | `/production/performance/:id/apply` | Apply an optimization |
| GET | `/production/high-availability` | HA topology |
| POST | `/production/failover` | Trigger manual failover |
| GET | `/production/disaster-recovery` | DR plan |
| POST | `/production/dr-drill` | Run DR drill |
| POST | `/production/audit` | Run production audit |
| GET | `/production/audits` | Audit history |

## System Validation (Batch 41)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| GET | `/validation/suites` | List 9 validation suites |
| POST | `/validation/run/:suiteId` | Run a single suite |
| POST | `/validation/run-all` | Run all suites sequentially |
| GET | `/validation/runs` | Validation run history |
| GET | `/validation/certification` | Production certification status |

## Auth & Security

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| POST | `/auth/register` | Register user (hashed password) |
| POST | `/auth/login` | Login -> JWT |
| GET | `/auth/me` | Current user |
| GET | `/users` | User list (admin) |
| GET | `/admin/audit` | Admin audit trail |

Auth is optional by default (`AUTH_REQUIRED=false`). When enabled, protected routes
require `Authorization: Bearer <jwt>` or `x-api-key` headers. All routes are
rate-limited via a token bucket (`/api/system/security` exposes limits).
