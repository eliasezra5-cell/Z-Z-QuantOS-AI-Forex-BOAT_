#!/usr/bin/env python3
"""
ZZ_QuantOS AI BOAT - MT5 Bridge

Runs ON the machine that has the MetaTrader 5 desktop terminal installed
(usually a Windows VPS or a Windows PC). It exposes a tiny REST API that the
QuantOS backend calls to read live quotes, place/close orders, and sync
account state with your real (or demo) MT5 broker account.

How it works
------------
  QuantOS backend (anywhere)  -->  this bridge (on MT5 machine)  -->  MT5 terminal
      MT5_BRIDGE_URL=http://<vps-ip>:5001            :5001                   broker

Requirements
------------
  pip install MetaTrader5 requests   (requests is optional; stdlib is used)

Run
---
  set MT5_LOGIN=12345678
  set MT5_PASSWORD=your_password
  set MT5_SERVER=YourBroker-Server
  python mt5_bridge.py

Then in the QuantOS backend set:
  MT5_ENABLED=live
  MT5_BRIDGE_URL=http://<mt5-machine-ip>:5001
"""

import json
import os
import time
from decimal import Decimal, ROUND_HALF_UP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

HOST = os.getenv("BRIDGE_HOST", "0.0.0.0")
PORT = int(os.getenv("BRIDGE_PORT", "5001"))
LOGIN = int(os.getenv("MT5_LOGIN", "0") or "0")
PASSWORD = os.getenv("MT5_PASSWORD", "")
SERVER = os.getenv("MT5_SERVER", "")
MT5_PATH = os.getenv("MT5_PATH", "")

SYMBOL_MAP = json.loads(os.getenv("MT5_SYMBOL_MAP", "{}"))

DEFAULT_SYMBOL_MAP = {
    "EURUSD": "EURUSD",
    "GBPUSD": "GBPUSD",
    "USDJPY": "USDJPY",
    "XAUUSD": "XAUUSD",
    "BTCUSD": "BTCUSD",
    "ETHUSD": "ETHUSD",
    "US500": "US500",
    "NAS100": "US100",
    "US30": "US30",
    "WTI": "USOIL",
    "AAPL": "AAPL",
    "TSLA": "TSLA",
}
DEFAULT_SYMBOL_MAP.update(SYMBOL_MAP)

_connected = False
_connect_time = 0
_start_time = time.time()


def ensure_connected():
    """Connect lazily and re-connect if the terminal disconnects."""
    global _connected, _connect_time
    if _connected and time.time() - _connect_time < 60:
        if mt5.terminal_info() is not None:
            return True
        _connected = False
    if mt5 is None:
        return False
    kwargs = {"login": LOGIN, "password": PASSWORD, "server": SERVER}
    if MT5_PATH:
        kwargs["path"] = MT5_PATH
    for attempt in range(3):
        try:
            if mt5.initialize(**kwargs):
                _connected = True
                _connect_time = time.time()
                return True
        except Exception as exc:  # pragma: no cover
            last_error = exc
            time.sleep(2)
            continue
    return False


def account_info():
    info = mt5.account_info()
    if info is None:
        return None
    return {
        "login": getattr(info, "login", None),
        "name": getattr(info, "name", None),
        "server": getattr(info, "server", None),
        "currency": getattr(info, "currency", None),
        "leverage": getattr(info, "leverage", None),
        "balance": round(getattr(info, "balance", 0.0) or 0.0, 2),
        "equity": round(getattr(info, "equity", 0.0) or 0.0, 2),
        "margin": round(getattr(info, "margin", 0.0) or 0.0, 2),
        "marginFree": round(getattr(info, "margin_free", 0.0) or 0.0, 2),
        "marginLevel": round(getattr(info, "margin_level", 0.0) or 0.0, 2),
        "openPositions": getattr(info, "positions", 0),
        "stopOutLevel": getattr(info, "margin_call", None),
    }


def to_mt5_symbol(sym):
    return DEFAULT_SYMBOL_MAP.get(sym.upper(), sym.upper())


def status_payload():
    connected = ensure_connected()
    latency = int((time.time() - _start_time) * 1000) if connected else 0
    payload = {
        "connected": connected,
        "mode": "live",
        "latency": latency,
        "bridgeTime": int(_start_time * 1000),
        "account": account_info() if connected else None,
    }
    if connected and payload["account"]:
        payload["account"]["broker"] = getattr(mt5.terminal_info(), "company", None)
        payload["account"]["build"] = getattr(mt5.terminal_info(), "build", None)
    return payload


def quote_payload(symbol):
    if not ensure_connected():
        return None
    name = to_mt5_symbol(symbol)
    tick = mt5.symbol_info_tick(name)
    info = mt5.symbol_info(name)
    if tick is None or info is None:
        return None
    return {
        "symbol": symbol,
        "bid": float(tick.bid),
        "ask": float(tick.ask),
        "spread": round(float(tick.ask - tick.bid), 5),
        "digits": int(info.digits),
        "sessionDeals": int(getattr(tick, "session_deals", 0)),
    }


def positions_payload():
    if not ensure_connected():
        return []
    out = []
    for pos in mt5.positions_get() or []:
        out.append({
            "ticket": pos.ticket,
            "symbol": pos.symbol,
            "side": "buy" if pos.type == 0 else "sell",
            "volume": float(pos.volume),
            "entryPrice": float(pos.price_open),
            "stopLoss": float(pos.sl) if pos.sl else None,
            "takeProfit": float(pos.tp) if pos.tp else None,
            "profit": round(float(pos.profit) + float(pos.swap) + float(pos.commission), 2),
            "time": pos.time * 1000,
        })
    return out


def orders_payload():
    if not ensure_connected():
        return []
    out = []
    for o in mt5.orders_get() or []:
        out.append({
            "ticket": o.ticket,
            "symbol": o.symbol,
            "side": "buy" if o.type in (0, 2) else "sell",
            "volume": float(o.volume_current),
            "price": float(o.price_open),
            "stopLoss": float(o.sl) if o.sl else None,
            "takeProfit": float(o.tp) if o.tp else None,
            "comment": o.comment,
            "time": o.time_setup * 1000,
        })
    return out


def history_payload(limit=100):
    if not ensure_connected():
        return []
    deals = mt5.history_deals_get(time.time() - 7 * 86400, time.time() + 60) or []
    out = []
    for d in deals[-limit:]:
        out.append({
            "ticket": d.ticket,
            "symbol": d.symbol,
            "side": "buy" if d.type in (0, 2) else "sell",
            "volume": float(d.volume),
            "price": float(d.price),
            "profit": round(float(d.profit), 2),
            "commission": round(float(d.commission), 2),
            "comment": d.comment,
            "time": d.time * 1000,
        })
    return out


def _enforce_stops_level(info, side, price, sl, tp):
    """Push SL/TP to at least broker stops_level points from the current price.

    Uses the live symbol_info.trade_stops_level / symbol_info.point so orders
    never reach MT5 with 'Invalid Stops' (SL/TP too close to the market).
    Decimal math, rounded to the symbol's digits. None values pass through.
    """
    stops_level = int(getattr(info, "trade_stops_level", 0) or 0)
    if stops_level <= 0:
        return sl, tp
    point = Decimal(str(getattr(info, "point", 0) or 0))
    if point <= 0:
        return sl, tp
    digits = int(getattr(info, "digits", 5) or 5)
    quantum = Decimal(1).scaleb(-digits)
    min_dist = point * stops_level
    entry = Decimal(str(price))
    side = (side or "buy").lower()

    def quantize(value):
        return float(value.quantize(quantum, rounding=ROUND_HALF_UP))

    if side == "buy":
        if sl and sl > 0:
            if entry - Decimal(str(sl)) < min_dist:
                sl = quantize(entry - min_dist)
        if tp and tp > 0:
            if Decimal(str(tp)) - entry < min_dist:
                tp = quantize(entry + min_dist)
    else:
        if sl and sl > 0:
            if Decimal(str(sl)) - entry < min_dist:
                sl = quantize(entry + min_dist)
        if tp and tp > 0:
            if entry - Decimal(str(tp)) < min_dist:
                tp = quantize(entry - min_dist)
    return sl, tp


def place_order(order):
    if not ensure_connected():
        return {"ok": False, "error": "not connected"}
    symbol = to_mt5_symbol(order.get("symbol", "EURUSD"))
    side = (order.get("side") or "buy").lower()
    volume = float(order.get("volume", 0.1))
    sl = float(order.get("stopLoss", 0.0) or 0.0)
    tp = float(order.get("takeProfit", 0.0) or 0.0)
    magic = int(order.get("magic", 0))
    comment = str(order.get("comment", "quantos"))[:31]
    info = mt5.symbol_info(symbol)
    if info is None:
        return {"ok": False, "error": f"symbol {symbol} not found on account"}
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return {"ok": False, "error": f"no live tick for {symbol}"}
    price = tick.ask if side == "buy" else tick.bid
    sl, tp = _enforce_stops_level(info, side, price, sl, tp)
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": sl or 0.0,
        "tp": tp or 0.0,
        "deviation": int(os.getenv("MT5_DEVIATION", "50")),
        "magic": magic,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        return {"ok": False, "retcode": getattr(result, "retcode", None), "comment": getattr(result, "comment", None)}
    return {
        "ok": True,
        "ticket": result.order,
        "price": float(result.price),
        "volume": float(result.volume),
        "comment": result.comment,
    }


def close_position(ticket):
    if not ensure_connected():
        return {"ok": False, "error": "not connected"}
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        return {"ok": False, "error": f"position {ticket} not found"}
    pos = positions[0]
    tick = mt5.symbol_info_tick(pos.symbol)
    side = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": pos.ticket,
        "symbol": pos.symbol,
        "volume": float(pos.volume),
        "type": side,
        "price": tick.bid if side == mt5.ORDER_TYPE_SELL else tick.ask,
        "deviation": int(os.getenv("MT5_DEVIATION", "50")),
        "magic": int(pos.magic),
        "comment": "quantos-close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        return {"ok": False, "retcode": getattr(result, "retcode", None), "comment": getattr(result, "comment", None)}
    return {"ok": True, "ticket": result.order, "comment": result.comment}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        query = {}
        if "?" in self.path:
            for part in self.path.split("?", 1)[1].split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    query[k] = v
        if path == "/status":
            self._send(200, status_payload())
        elif path == "/quotes":
            syms = (query.get("symbols") or "EURUSD,XAUUSD").split(",")
            self._send(200, [q for q in (quote_payload(s) for s in syms) if q])
        elif path == "/positions":
            self._send(200, positions_payload())
        elif path == "/orders":
            self._send(200, orders_payload())
        elif path == "/history":
            self._send(200, history_payload(int(query.get("limit", "100"))))
        elif path == "/health":
            self._send(200, {"ok": True, "mt5": mt5 is not None})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        body = self._read_json()
        if path == "/orders":
            self._send(200, place_order(body))
        elif path == "/disconnect":
            global _connected
            if mt5 is not None:
                mt5.shutdown()
            _connected = False
            self._send(200, {"ok": True})
        elif path.startswith("/positions/") and path.endswith("/close"):
            ticket = int(path.split("/")[2])
            self._send(200, close_position(ticket))
        else:
            self._send(404, {"error": "not found"})


def main():
    print("=" * 62)
    print("  ZZ_QuantOS AI BOAT - MT5 Bridge")
    print("  MT5 installed:", mt5 is not None)
    print(f"  Account: {LOGIN} @ {SERVER or '(default server)'}")
    print(f"  Listening on http://{HOST}:{PORT}")
    print("=" * 62)
    if mt5 is None:
        print("  [WARN] MetaTrader5 package not found. Run:  pip install MetaTrader5")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        if mt5 is not None:
            mt5.shutdown()
        print("\nBridge stopped.")


if __name__ == "__main__":
    main()
