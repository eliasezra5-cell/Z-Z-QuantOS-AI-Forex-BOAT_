"""Secure TradingView webhook receiver (additive Module 3.2).

Accepts external TradingView alerts and routes them through the Risk Engine
(strict risk policy pre-trade gate + capital protection). The signal can NEVER
bypass the risk engine — even an approved signal only creates a suggested trade
record that still has to pass the same gate at execution time.

Security model:
  - HMAC-SHA256 signature verification (constant-time) against the configured
    secret (``TRADINGVIEW_WEBHOOK_SECRET`` or the integration config secret).
  - Optional timestamp replay-window check.
  - The webhook body is used verbatim for signature verification (never a
    re-serialized copy) so signature mismatches cannot be hidden.
"""
import hashlib
import hmac
import time
import urllib.parse

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db

DEFAULT_MAX_SKEW_SECONDS = 300

_ACTION_ALIASES = {"buy": "buy", "long": "buy", "bullish": "buy", "sell": "sell", "short": "sell", "bearish": "sell"}


def _env(key):
    import os
    return os.environ.get(key, "")


class TradingViewWebhookError(Exception):
    """Raised when the webhook is rejected (bad signature / bad payload)."""


class TradingViewWebhook:
    """Validates and risk-gates TradingView alert webhooks."""

    id = "tradingview"
    name = "TradingView Webhook (secure)"

    def __init__(self, secret=None, max_skew_seconds=DEFAULT_MAX_SKEW_SECONDS):
        self.secret = (secret or _env("TRADINGVIEW_WEBHOOK_SECRET") or "").encode("utf-8")
        self.max_skew_seconds = max_skew_seconds

    # ------------------------------------------------------------------ #
    # Signature verification
    # ------------------------------------------------------------------ #
    def verify_signature(self, payload_bytes, signature, timestamp=None):
        """Constant-time HMAC-SHA256 check of the raw body.

        ``payload_bytes`` MUST be the exact raw request body. When a timestamp
        is provided (the ``X-Webhook-Timestamp`` header), a replay-window check
        is also applied.
        """
        if not signature or not self.secret:
            return False
        if timestamp is not None:
            try:
                ts = int(timestamp)
            except (TypeError, ValueError):
                return False
            if abs(int(time.time()) - ts) > self.max_skew_seconds:
                return False
        body = payload_bytes if isinstance(payload_bytes, bytes) else str(payload_bytes).encode("utf-8")
        digest = hmac.new(self.secret, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(digest, str(signature))

    # ------------------------------------------------------------------ #
    # Signal normalization
    # ------------------------------------------------------------------ #
    def normalize_alert(self, payload):
        """Turn a raw TradingView payload into a normalized signal dict."""
        action_raw = str(payload.get("action") or "").lower()
        action = _ACTION_ALIASES.get(action_raw, action_raw or "unknown")
        price = payload.get("price")
        try:
            price = float(price)
        except (TypeError, ValueError):
            price = None
        return {
            "symbol": payload.get("symbol"),
            "action": action,
            "price": price,
            "source": "tradingview",
            "strategy": payload.get("strategy"),
            "timeframe": payload.get("timeframe"),
            "confidence": payload.get("confidence"),
            "alertTime": payload.get("time") or int(time.time() * 1000),
            "receivedAt": int(time.time() * 1000),
            "raw": payload,
        }

    # ------------------------------------------------------------------ #
    # Risk gating (the signal can NEVER bypass the risk engine)
    # ------------------------------------------------------------------ #
    def risk_gate(self, signal):
        """Run the signal through the strict risk policy pre-trade gate.

        Returns a result dict; when ``approved`` is False the ``reasons`` field
        explains why. This is the single choke point for external signals.
        """
        from ..risk.strict_risk_policy import strict_risk_policy  # lazy import

        symbol = signal.get("symbol")
        blocked, reasons = strict_risk_policy.pre_trade_gate(
            {
                "symbol": symbol,
                "side": signal.get("action"),
                "source": "tradingview",
                "volume": 0.1,
            },
            spread_points=_spread_points(symbol),
        )
        result = {
            "source": "tradingview",
            "symbol": symbol,
            "side": signal.get("action"),
            "approved": not blocked,
            "reasons": reasons,
            "signal": signal,
            "timestamp": int(time.time() * 1000),
        }
        event_bus.emit("tradingview:risk-gated", result)
        return result

    def process(self, payload_bytes, signature, timestamp=None, payload=None):
        """Full pipeline: verify signature -> normalize -> risk gate.

        Returns a result with ``accepted`` (signature ok) and ``approved``
        (risk gate passed). Approved signals are recorded as suggested trades.
        """
        if not self.verify_signature(payload_bytes, signature, timestamp):
            raise TradingViewWebhookError("invalid-signature")
        data = payload if payload is not None else _decode_json(payload_bytes)
        signal = self.normalize_alert(data)
        gated = self.risk_gate(signal)
        record = {
            **gated,
            "signatureValid": True,
            "receivedAt": int(time.time() * 1000),
        }
        db.collection("tradingview_alerts").insert(record)
        if gated["approved"]:
            self._create_suggestion(signal)
        return gated

    def _create_suggestion(self, signal):
        """Record an approved external signal as a suggested trade.

        Note: this does NOT place an order. Execution (if enabled at all) goes
        through the normal trading engine which re-runs the pre-trade gate.
        """
        row = db.collection("suggested_trades").insert({
            "symbol": signal.get("symbol"),
            "side": signal.get("action"),
            "volume": 0.1,
            "price": signal.get("price"),
            "confidence": signal.get("confidence"),
            "source": "tradingview",
            "approved": False,
            "createdAt": int(time.time() * 1000),
            "strategy": signal.get("strategy"),
            "timeframe": signal.get("timeframe"),
        })
        event_bus.emit("tradingview:suggested", {"suggestionId": row["id"], "symbol": signal.get("symbol")})
        return row

    # ------------------------------------------------------------------ #
    def self_test(self):
        return {"success": bool(self.secret), "detail": "signing secret present" if self.secret else "signing secret missing"}


def _decode_json(payload_bytes):
    import json

    if isinstance(payload_bytes, bytes):
        return json.loads(payload_bytes.decode("utf-8"))
    if isinstance(payload_bytes, (dict, list)):
        return payload_bytes
    return json.loads(str(payload_bytes))


def _spread_points(symbol):
    try:
        from ..marketdata.engine import get_quote  # lazy import
        quote = get_quote(symbol)
        bid = quote.get("bid")
        ask = quote.get("ask")
        if bid and ask:
            return round(abs(float(ask) - float(bid)) * 10000, 1)
    except Exception:  # noqa: BLE001 - quote unavailable
        return None
    return None


def _validate_webhook_url(url):
    """Validate a URL before it is used in the TradingView flow."""
    try:
        parts = urllib.parse.urlparse(url)
    except ValueError:
        return {"valid": False, "reason": "malformed-url"}
    if parts.scheme not in ("http", "https"):
        return {"valid": False, "reason": "unsupported-scheme"}
    if not parts.netloc:
        return {"valid": False, "reason": "missing-host"}
    return {"valid": True, "host": parts.netloc}


tradingview_webhook = TradingViewWebhook()


def init_tradingview_webhook():
    secret = _env("TRADINGVIEW_WEBHOOK_SECRET")
    if secret:
        tradingview_webhook.secret = secret.encode("utf-8")
    logger.info(f"TradingView webhook initialized (secret={'configured' if tradingview_webhook.secret else 'missing'})")
    return tradingview_webhook
