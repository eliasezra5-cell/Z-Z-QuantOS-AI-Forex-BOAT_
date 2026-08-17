"""Live slippage / execution-cost tracking on filled trades (Feature 3).

Proves the additive fill-tracking fields are written to both the order and the
position record at fill time:

  * ``expectedFillPrice``  — fair-value mid adjusted by the estimated cost-per-unit
  * ``actualFillPrice``    — the price the order actually filled at
  * ``spreadCost``         — spread * volume paid on the fill
  * ``actualSlippage`` / ``actualSlippagePips`` — realized |expected-actual| gap

Existing cost fields (spread, spreadPips, estimatedSlippage, ...) must remain
untouched, and rejected orders must not carry fill-tracking fields.

Run with: python3 -m pytest app/tests/test_live_execution_costs.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_live_costs_test")
os.environ["POSTGRES_ENABLED"] = "false"
os.environ["DATABASE_URL"] = ""

from app.foundation.json_store import db  # noqa: E402
from app.modules.trading.engine import trading_engine  # noqa: E402
from app.modules.execution.mt5_safety import mt5_safety  # noqa: E402
from app.modules.mt5.adapter import mt5_state  # noqa: E402


def _reset():
    for name in ("positions", "orders", "news_traded", "mt5_safety_orders", "mt5_frozen_symbols", "mt5_reconciliation"):
        db.collection(name).clear()
    for f in mt5_safety.frozen_symbols():
        mt5_safety.unfreeze_symbol(f["symbol"])
    mt5_state.connected = False


def _valid_order(**over):
    price = 4300.0
    return {
        "symbol": "XAUUSD",
        "side": "buy",
        "volume": 0.1,
        "price": price,
        "stopLoss": round(price - 5, 5),
        "takeProfit": round(price + 10, 5),
        "source": "ai-decision",
        **over,
    }


# --------------------------------------------------------------------------- #
# 1. Filled order carries all fill-tracking fields (additive)
# --------------------------------------------------------------------------- #
def test_filled_order_carries_fill_tracking_fields():
    _reset()
    res = trading_engine.place_order(_valid_order())
    assert res["status"] == "filled"
    order = res["order"]
    for key in ("expectedFillPrice", "actualFillPrice", "spreadCost", "actualSlippage", "actualSlippagePips"):
        assert key in order, f"missing {key} on filled order"
    assert order["expectedFillPrice"] > 0
    assert order["actualFillPrice"] == order["price"]
    assert order["spreadCost"] >= 0
    assert order["actualSlippage"] >= 0
    assert order["actualSlippagePips"] >= 0


# --------------------------------------------------------------------------- #
# 2. Position carries the same fill-tracking fields (additive)
# --------------------------------------------------------------------------- #
def test_filled_position_carries_fill_tracking_fields():
    _reset()
    res = trading_engine.place_order(_valid_order())
    assert res["status"] == "filled"
    pos = res["position"]
    for key in ("expectedFillPrice", "actualFillPrice", "spreadCost", "actualSlippage", "actualSlippagePips"):
        assert key in pos, f"missing {key} on filled position"
    assert pos["actualFillPrice"] == pos["entryPrice"]


# --------------------------------------------------------------------------- #
# 3. Existing cost fields remain untouched
# --------------------------------------------------------------------------- #
def test_existing_cost_fields_unchanged():
    _reset()
    res = trading_engine.place_order(_valid_order())
    assert res["status"] == "filled"
    order = res["order"]
    for key in ("spread", "spreadPips", "estimatedSlippagePips", "estimatedSlippage", "estimatedCostPerUnit"):
        assert key in order, f"missing pre-existing cost field {key}"
    pos = res["position"]
    for key in ("spread", "spreadPips", "currentSpread", "currentSpreadPips", "estimatedSlippagePips", "estimatedSlippage", "estimatedCostPerUnit"):
        assert key in pos, f"missing pre-existing cost field {key}"


# --------------------------------------------------------------------------- #
# 4. Buy vs sell side: expected fill is worse than fair-value mid on both
# --------------------------------------------------------------------------- #
def test_buy_expected_fill_worse_than_mid():
    _reset()
    # no explicit price -> engine fills at the live ask, expected fill is the
    # mid plus estimated cost-per-unit, so expected is worse (higher) for buy
    order = _valid_order(side="buy", price=None)
    res = trading_engine.place_order(order)
    assert res["status"] == "filled"
    o = res["order"]
    assert o["expectedFillPrice"] >= o["actualFillPrice"]


def test_sell_expected_fill_worse_than_mid():
    _reset()
    # no explicit price -> engine fills at the live bid, expected fill is the
    # mid minus estimated cost-per-unit, so expected is worse (lower) for sell
    order = _valid_order(side="sell", price=None)
    res = trading_engine.place_order(order)
    assert res["status"] == "filled"
    o = res["order"]
    assert o["expectedFillPrice"] <= o["actualFillPrice"]


# --------------------------------------------------------------------------- #
# 5. Volume scales spread cost
# --------------------------------------------------------------------------- #
def test_spread_cost_scales_with_volume():
    _reset()
    small = trading_engine.place_order(_valid_order(volume=0.1, idempotency_key="vol-1", newsFingerprint="vol-n1"))["order"]
    big = trading_engine.place_order(_valid_order(volume=0.2, idempotency_key="vol-2", newsFingerprint="vol-n2"))["order"]
    assert big["spreadCost"] == round(small["spreadCost"] * 2, 2)


# --------------------------------------------------------------------------- #
# 6. Rejected orders never carry fill-tracking fields
# --------------------------------------------------------------------------- #
def test_rejected_order_has_no_fill_tracking():
    _reset()
    res = trading_engine.place_order(_valid_order(volume=0.5, idempotency_key="dup-reject"))
    assert res["status"] == "filled"
    dup = trading_engine.place_order(_valid_order(volume=0.5, idempotency_key="dup-reject"))
    assert dup["status"] == "rejected"
    for key in ("expectedFillPrice", "actualFillPrice", "spreadCost", "actualSlippage", "actualSlippagePips"):
        assert key not in dup["order"], f"rejected order must not carry {key}"
