# Social Bot Commands — Per-Platform Guide (Urdu/English)

Project: ZZ_QuantOS AI BOAT

Yeh guide batata hai ke **har social platform par alag alag** kaunsa command
chalta hai. Telegram, WhatsApp aur Email — teeno ke liye complete list.

---

## RULE YAAD RAKHO

- `/` wale commands (slash) **teeno platforms par** chalte hain — Telegram,
  WhatsApp aur Email (same exact commands).
- **Natural language** commands (bina `/` ke English sentences) **teeno
  platforms par same** chalte hain.
- `1` = approve, `2` = reject — **teeno platforms par** kaam karta hai.
- Roman Urdu mein free chat bhi chalti hai — bot usi language mein jawab deta hai.

---

## 📱 TELEGRAM — SABSE ZYADA COMMANDS

### Slash commands

| Command | Kaam |
|---------|------|
| `/status` | Mode, capital shield, emergency stop, positions check karo |
| `/trades` | Open positions dekho |
| `/ask <sawal>` | AI se sawal poocho (e.g. `/ask kya aaj gold buy karna chahiye?`) |
| `/approve <id>` | Koi specific suggestion approve karo |
| `/reject <id>` | Koi specific suggestion reject karo |
| `/prefs` | Saved preferences dekho |
| `/forget <id>` | Koi preference delete karo |

### Natural language (bina slash ke)

- `switch to semi auto`
- `switch to full auto`
- `switch to analysis only`
- `emergency stop now`
- `clear emergency stop`
- `set risk to 1%`
- `set daily loss to 3`
- `set max open positions to 5`
- `set max exposure to 10%`
- `set auto threshold to 90%`
- `set suggest threshold to 70%`
- `place buy order XAUUSD lot 0.1 sl 2450 tp 2500`
- `place sell order EURUSD lot 0.2`
- `close XAUUSD position`
- `close all open positions`
- `reverse EURUSD position`
- `trigger kill switch market_data_stale`
- `clear kill switch market_data_stale`
- `clear all kill switches`
- `freeze XAUUSD`
- `unfreeze XAUUSD`
- `raise hard blocker news_safety`
- `clear hard blocker news_safety`
- `pause kill condition daily_loss_limit for 30 min`
- `clear pause on daily_loss_limit`
- `set trading hours 8-20`
- `clear all trading schedules`
- `analysis on XAUUSD`
- `run all news collectors`
- `remember that never trade GBPUSD`

### Quick reply
- `1` = approve / `2` = reject

---

## 💬 WHATSAPP — SAB SLASH COMMANDS AB YAHAN BHI

### Slash commands (same as Telegram)

| Command | Kaam |
|---------|------|
| `/status` | Mode, capital shield, emergency stop, positions check karo |
| `/trades` | Open positions dekho |
| `/ask <sawal>` | AI se sawal poocho (e.g. `/ask kya aaj gold buy karna chahiye?`) |
| `/approve <id>` | Koi specific suggestion approve karo |
| `/reject <id>` | Koi specific suggestion reject karo |
| `/prefs` | Saved preferences dekho |
| `/forget <id>` | Koi preference delete karo |

### Quick reply
- `1` = approve / `2` = reject

### Natural language (wohi sab commands)

- `switch to semi auto`
- `switch to full auto`
- `switch to analysis only`
- `emergency stop now`
- `clear emergency stop`
- `set risk to 1%`
- `set daily loss to 3`
- `set max open positions to 5`
- `set max exposure to 10%`
- `set auto threshold to 90%`
- `set suggest threshold to 70%`
- `place buy order XAUUSD lot 0.1 sl 2450 tp 2500`
- `place sell order EURUSD lot 0.2`
- `close XAUUSD position`
- `close all open positions`
- `reverse EURUSD position`
- `trigger kill switch market_data_stale`
- `clear kill switch market_data_stale`
- `clear all kill switches`
- `freeze XAUUSD`
- `unfreeze XAUUSD`
- `raise hard blocker news_safety`
- `clear hard blocker news_safety`
- `pause kill condition daily_loss_limit for 30 min`
- `clear pause on daily_loss_limit`
- `set trading hours 8-20`
- `clear all trading schedules`
- `analysis on XAUUSD`
- `run all news collectors`
- `remember that never trade GBPUSD`

### News forward
- Koi bhi news text forward karo → AI analyze karta hai, News Terminal mein
  live dikhti hai, reply: "News received. AI is analyzing..."

⚠️ **Note:** WhatsApp par `1` ya `2` news ke liye use na karein — wo
approve/reject samjha jata hai.

---

## 📧 EMAIL — ALLOWED SENDER SE, ~60 SEC POLL

### Slash commands (same as Telegram)

| Command | Kaam |
|---------|------|
| `/status` | Mode, capital shield, emergency stop, positions check karo |
| `/trades` | Open positions dekho |
| `/ask <sawal>` | AI se sawal poocho (e.g. `/ask kya aaj gold buy karna chahiye?`) |
| `/approve <id>` | Koi specific suggestion approve karo |
| `/reject <id>` | Koi specific suggestion reject karo |
| `/prefs` | Saved preferences dekho |
| `/forget <id>` | Koi preference delete karo |

### Quick reply
- `1` = approve / `2` = reject

### Specific approve/reject
- `/approve <id>`
- `/reject <id>`

### Natural language (email body mein, wohi sab commands)

- `switch to semi auto`
- `switch to full auto`
- `switch to analysis only`
- `emergency stop now`
- `clear emergency stop`
- `set risk to 1%`
- `set daily loss to 3`
- `set max open positions to 5`
- `set max exposure to 10%`
- `set auto threshold to 90%`
- `set suggest threshold to 70%`
- `place buy order XAUUSD lot 0.1 sl 2450 tp 2500`
- `place sell order EURUSD lot 0.2`
- `close XAUUSD position`
- `close all open positions`
- `reverse EURUSD position`
- `trigger kill switch market_data_stale`
- `clear all kill switches`
- `freeze XAUUSD`
- `unfreeze XAUUSD`
- `set trading hours 8-20`
- `analysis on XAUUSD`
- `run all news collectors`
- `remember that never trade GBPUSD`

---

## 📊 EK NAZAR TABLE

| Command | Telegram | WhatsApp | Email |
|---------|:--------:|:--------:|:-----:|
| `1` / `2` (approve/reject) | ✅ | ✅ | ✅ |
| `/status`, `/trades`, `/ask`, `/prefs`, `/forget` | ✅ | ✅ | ✅ |
| `/approve <id>`, `/reject <id>` | ✅ | ✅ | ✅ |
| Natural language (risk, modes, orders, safety...) | ✅ | ✅ | ✅ |
| News forward | ✅ | ✅ | ❌ |
| Roman Urdu free chat | ✅ | ✅ | ✅ |

---

## ZAROORI BAATEIN

- Natural-language commands English keyword phrases hain — upar wali shape mein
  hi bhejein.
- `1` / `2` har channel par approve/reject ke liye reserved hain.
- Har trade risk-engine, validation engine, capital protection aur hard
  blockers se guzarti hai — bot safety kabhi bypass nahi karta.
- Agar channel configured nahi hai (token/credentials missing), message outbox
  mein `pending` ho jata hai — system chalta rahta hai.
