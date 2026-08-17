# Connecting a Real MT5 Account to ZZ_QuantOS

This platform runs on a cloud server, so it cannot run the MetaTrader 5 desktop
terminal directly. To trade a **real or demo MT5 account**, you connect the
QuantOS backend to a small **MT5 Bridge** that runs next to your MT5 terminal
(usually a Windows VPS or Windows PC).

```
  QUANTOS BACKEND (cloud)                YOUR MACHINE (Windows VPS / PC)
  ─────────────────────                  ────────────────────────────────
  backend-py/app/modules/mt5/adapter.py  →  bridge/mt5_bridge.py  →  MT5 terminal
  MT5_BRIDGE_URL=http://<ip>:5001        (port 5001)                ↓
                                                                   Broker
```

## 1. Run the MT5 Bridge on your trading machine

**Prerequisites**

1. Install the **MetaTrader 5 desktop terminal** from your broker and log in to
   your account (demo is strongly recommended first). Keep the terminal open.
2. Install Python 3.9+ and the official MetaTrader5 module:

   ```
   pip install MetaTrader5
   ```

3. Copy `bridge/mt5_bridge.py` from this repo to that machine.

**Start the bridge**

```bash
# Windows (cmd)
set MT5_LOGIN=12345678
set MT5_PASSWORD=YourPassword
set MT5_SERVER=YourBroker-Server
python mt5_bridge.py

# Linux (if your broker offers a headless terminal)
MT5_LOGIN=12345678 MT5_PASSWORD=YourPassword MT5_SERVER=YourBroker-Server \
  MT5_PATH="~/.wine/drive_c/Program Files/Broker/terminal64.exe" \
  python3 mt5_bridge.py
```

Optional variables:

| Env var | Default | Purpose |
|---------|---------|---------|
| `BRIDGE_HOST` | `0.0.0.0` | Interface the bridge listens on |
| `BRIDGE_PORT` | `5001` | HTTP port for the bridge |
| `MT5_SYMBOL_MAP` | built-in map | JSON remap, e.g. `{"US500":"SP500","WTI":"WTIUSD"}` |
| `MT5_DEVIATION` | `50` | Max price deviation in points |
| `MT5_PATH` | auto | Path to `terminal64.exe` (Linux) |

Verify it works locally:

```
curl http://127.0.0.1:5001/status
curl "http://127.0.0.1:5001/quotes?symbols=XAUUSD,EURUSD,BTCUSD"
```

## 2. Point QuantOS at the bridge

Set these environment variables when starting the backend:

```bash
export MT5_ENABLED=live
export MT5_BRIDGE_URL=http://<your-mt5-machine-ip>:5001
export MT5_LOGIN=12345678      # optional, for reference
export MT5_PASSWORD=******     # optional, for reference
```

Restart the backend:

```
bash start.sh   # or however you launch it
```

The MT5 module now routes **all execution through your real account**:

- `GET  /api/mt5/status`    → live account state from the terminal
- `GET  /api/mt5/positions` → your broker's open positions
- `GET  /api/mt5/history`   → your broker's closed deals
- `POST /api/mt5/orders`    → market order on your account (risk-checked first)
- `POST /api/mt5/positions/{ticket}/close` → close a live position

The **Trading Engine** page in the UI shows `Connected` when the bridge is
reachable. If the bridge is unreachable, the backend logs a warning and stays in
demo simulation so the dashboard keeps working.

## 3. Demo (no MT5 needed)

By default (`MT5_ENABLED=demo`) the platform simulates a broker account
(ICMarkets-style demo) with full order lifecycle, P&L and risk checks, so you can
develop and validate strategies without any broker. Switch to `live` only when
you are ready to trade real money.

## 4. Trading modes

| Mode | Execution |
|------|-----------|
| Manual | Orders placed from the Trading Engine page go straight to MT5 |
| Auto   | AI decisions from the decision pipeline auto-execute on MT5 (see `/api/execution/evaluate`), gated by risk manager + confidence checks |

## 5. Risk & capital protection

Regardless of manual/auto or demo/live, every order passes through the risk
engine first: max drawdown, max correlation, max open positions, daily loss
limit, capital-protection halt flag, and position sizing with dynamic SL/TP.

## 6. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `/status` returns `connected:false` | Keep the MT5 terminal open and logged in on the bridge machine |
| Bridge unreachable from cloud | Open firewall port 5001 on the bridge machine / VPS |
| `symbol not found on account` | Adjust `MT5_SYMBOL_MAP` to your broker's symbol names |
| `retcode: 10004 (no money)` | Not enough free margin on the account |
| MetaTrader5 not installed | `pip install MetaTrader5` on the bridge machine |
