# Social Bot Command Reference — Telegram · WhatsApp · Email

Project: ZZ_QuantOS AI BOAT (AI Forex Trading Operating System)

Use this guide to control the entire trading system from your phone/desktop via
the social bot — no need to open the Admin Panel or frontend.

---

## 1. Channel capabilities at a glance

| Command type                       | Telegram | WhatsApp | Email |
|------------------------------------|:--------:|:--------:|:-----:|
| Slash commands (`/status`, `/trades`, `/approve <id>`, `/reject <id>`, `/ask`, `/prefs`, `/forget`) | ✅ | ✅ | ✅ |
| Quick approve / reject (`1` / `2`) | ✅ | ✅ | ✅ |
| Natural-language control intents (risk, modes, orders, safety…) | ✅ | ✅ | ✅ |
| Free-form AI chat                  | ✅ | ✅ | ✅ |
| Manual-forward news ingestion      | ✅ | ✅ | ❌ |

- **Telegram**, **WhatsApp** and **Email** all expose the same slash commands
  (full command parity), plus intents and free-form chat.
- The `1` / `2` quick reply always acts on the **most recent pending suggestion**.

---

## 2. Quick approve / reject (works on ALL channels)

This is the semi-auto loop: the AI creates a suggestion (70–89% confidence),
an alert arrives on your channel, and you approve or reject it.

| You send | Meaning |
|----------|---------|
| `1` | Approve the latest pending suggestion → goes to risk-gated execution |
| `2` | Reject the latest pending suggestion |

Reply you get: e.g. `XAUUSD buy (approved)` or `EURUSD sell (rejected)`.

### Telegram / Email — approve/reject a specific suggestion by ID

| Command | Meaning |
|---------|---------|
| `/approve <suggestedTradeId>` | Approve a specific pending suggestion |
| `/reject <suggestedTradeId>` | Reject a specific pending suggestion |

Example: `/approve dd874067-208`

---

## 3. Slash commands (same on Telegram, WhatsApp and Email)

| Command | Meaning |
|---------|---------|
| `/status` | Trading mode, capital shield, emergency stop, equity, daily loss, open positions |
| `/trades` | List open positions (symbol, side, volume, profit) |
| `/approve <id>` | Approve a pending suggested trade (risk-gated) |
| `/reject <id>` | Reject a pending suggested trade |
| `/ask <question>` | Force an AI reply to an explicit question |
| `/prefs` | List saved user preferences |
| `/forget <id>` | Delete one saved preference |
| `1` / `2` | Approve / reject the most recent pending suggestion |

On WhatsApp, send the slash command as the message text (e.g. `/status`). On
Email, put it as the email body (first line). All channels support the full set.

---

## 4. Natural-language control commands (all channels)

These use the same intent engine as the Admin Panel. Send them exactly in this
shape (English keywords). Where you see a value in brackets, replace it.

### 4.1 Risk limits

| Intent | Example |
|--------|---------|
| Set max risk per trade % | `set risk to 2%` |
| Set max daily loss % | `set daily loss to 3` |
| Set max open positions | `set max open positions to 5` |
| Set max total exposure % | `set max exposure to 10%` |

### 4.2 Trading modes

| Intent | Example |
|--------|---------|
| Switch to ANALYSIS_ONLY | `switch to analysis only` |
| Switch to SEMI_AUTO | `switch to semi auto` |
| Switch to AUTO_FULL | `switch to full auto` |
| Emergency stop now | `emergency stop now` |
| Clear emergency stop | `clear emergency stop` |

### 4.3 Risk profile & confidence gates

| Intent | Example |
|--------|---------|
| Set risk profile | `set profile to aggressive` (also: conservative, scalping, swing) |
| Set auto-execute threshold | `set auto threshold to 90%` |
| Set suggest threshold | `set suggest threshold to 70%` |

### 4.4 Kill switches / fail-closed / reset

| Intent | Example |
|--------|---------|
| Trigger a kill switch | `trigger kill switch daily_loss_limit` |
| Clear a kill switch | `clear kill switch market_data_stale` |
| Clear all kill switches + reset | `clear all kill switches` |
| Raise a fail-closed trigger | `trigger fail closed mt5_disconnected` |
| Clear a fail-closed trigger | `clear fail closed mt5_disconnected` |

Valid kill-switch / fail-closed names:
`daily_loss_limit`, `weekly_loss_limit`, `equity_below_80pct`,
`max_drawdown_exceeded`, `five_consecutive_losses`, `mt5_disconnected`,
`market_data_stale`, `ai_provider_failure`, `weekend`, `major_news_in_30m`,
`capital_shield_red`

### 4.5 Trading schedules

| Intent | Example |
|--------|---------|
| Add trading hours | `set trading hours 8-20` (0–23, start before end, UTC) |
| Clear all schedules | `clear all trading schedules` |

### 4.6 Manual orders & position management

| Intent | Example |
|--------|---------|
| Place a market order | `place buy order XAUUSD lot 0.1 sl 2450 tp 2500` |
| Close a symbol's position | `close XAUUSD position` |
| Reverse a symbol's position | `reverse EURUSD position` |
| Close everything | `close all open positions` |

Order parameters after the symbol: `lot <n>`, `sl <price>`, `tp <price>`.
Orders still go through the safety gate — rejected if violated.

### 4.7 MT5 safety (freeze symbols)

| Intent | Example |
|--------|---------|
| Freeze a symbol | `freeze XAUUSD` |
| Unfreeze a symbol | `unfreeze XAUUSD` |

### 4.8 Hard blockers (validation engine)

| Intent | Example |
|--------|---------|
| Raise a hard blocker | `raise hard blocker news_safety` |
| Clear a hard blocker | `clear hard blocker news_safety` |

### 4.9 Brain / kill-switch pauses (brain monitor)

| Intent | Example |
|--------|---------|
| Pause a condition | `pause kill condition daily_loss_limit for 30 min` |
| Clear a pause | `clear pause on daily_loss_limit` |

Condition names are the same kill-switch list as section 4.4.

### 4.10 News & analysis

| Intent | Example |
|--------|---------|
| Run all news collectors | `run all news collectors` |
| Run AI analysis on a symbol | `analysis on XAUUSD` |

---

## 5. Preferences (long-term memory)

Teach the bot rules it must follow. Preferences persist in AI memory.

| Intent | Example |
|--------|---------|
| Remember a rule | `remember that never trade GBPUSD` |
| Any preference phrase | `my preference is risk per trade max 1%` |
| List saved preferences | `/prefs` (all channels) |
| Forget one preference | `/forget <preferenceId>` (all channels) |

Hard constraints like `never trade GBPUSD` become real blockers: they are
injected into the auto-trade gate and block that symbol.

---

## 6. Manual-forward news ingestion

Any non-command message you forward into the bot is treated as a news event
and goes through the AI news pipeline (analysis → 5-agent decision → News
Terminal, live on the frontend).

- **WhatsApp:** forward any news text → bot replies `News received. AI is analyzing...`
- **Telegram:** send any text that is not a `/command` or `1`/`2` → same pipeline

Do NOT use `1` or `2` as news forwards — those are reserved for approve/reject.

---

## 7. Example end-to-end flows

### Semi-auto approval over WhatsApp
1. AI creates suggestion → WhatsApp alert:
   `AI Suggests: BUY XAUUSD. Conf: 75%. Reply '1' to Execute, '2' to Reject.`
2. You reply `1` → bot: `XAUUSD buy (approved)`
3. Trade goes through the risk gate → execution report sent to Telegram +
   WhatsApp + Email.

### Full control over Telegram
1. `/status` → check mode/shield/positions
2. `switch to semi auto` → enable suggestion flow
3. `set risk to 1%` → tighten risk
4. `set trading hours 8-20` → restrict to a session
5. `1` → approve the pending suggestion when the alert arrives
6. `/trades` → verify the position is open

---

## 8. Important notes

- Natural-language intents are **English keyword phrases**; keep the exact
  verb/noun order shown above.
- `1` and `2` are reserved for approve/reject on every channel.
- All execution still passes through the risk engine, validation engine,
  capital protection, and hard blockers — the bot never bypasses safety gates.
- When a channel is not configured (no token/credentials), messages are
  recorded to the integration outbox as `pending` — the system keeps working.
- Free-form chat falls back to a live status summary if no AI provider is
  reachable.
