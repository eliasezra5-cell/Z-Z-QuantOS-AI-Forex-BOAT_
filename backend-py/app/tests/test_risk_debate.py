"""Unit tests for Feature 3 — Risk Debate Team + Portfolio Gate."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_risk_debate_test")

from unittest import mock  # noqa: E402

import pytest  # noqa: E402

from app.foundation.json_store import db  # noqa: E402
from app.modules.risk.debate.officers import (  # noqa: E402
    AGGRESSIVE_OFFICER,
    CONSERVATIVE_OFFICER,
    NEUTRAL_OFFICER,
    resolve_debate,
)
from app.modules.risk.debate.portfolio_gate import (  # noqa: E402
    build_gate_context,
    run_portfolio_gate,
    get_latest_risk_debate,
)
from app.modules.risk.debate import debate_order  # noqa: E402
from app.modules.trading.engine import trading_engine  # noqa: E402
from app.modules.execution.mt5_safety import mt5_safety  # noqa: E402


def _reset():
    for name in ("positions", "orders", "news_traded", "mt5_safety_orders", "mt5_frozen_symbols", "mt5_reconciliation"):
        db.collection(name).clear()
    for f in mt5_safety.frozen_symbols():
        mt5_safety.unfreeze_symbol(f["symbol"])


def _ctx(volume=0.1, notional_pct=5.0, risk_pct=1.0, stop_loss=4295.0, equity=10000.0):
    return {
        "symbol": "XAUUSD",
        "side": "buy",
        "volume": volume,
        "notional": 4300.0 * volume,
        "notionalPct": notional_pct,
        "riskAmount": abs(4300.0 - stop_loss) * volume if stop_loss else 0,
        "riskAmountPct": risk_pct,
        "stopLoss": stop_loss,
        "takeProfit": 4310.0,
        "confidence": 0.8,
        "openPositions": 1,
        "equity": equity,
    }


def test_aggressive_approves_moderate_risk():
    v = AGGRESSIVE_OFFICER(_ctx())
    assert v["verdict"] == "approve"
    assert v["maxVolume"] == 0.1


def test_aggressive_rejects_extreme_exposure():
    v = AGGRESSIVE_OFFICER(_ctx(risk_pct=9.0))
    assert v["verdict"] == "reject"


def test_conservative_rejects_high_exposure():
    v = CONSERVATIVE_OFFICER(_ctx(risk_pct=5.0))
    assert v["verdict"] == "reject"


def test_conservative_reduces_on_missing_stop_loss():
    v = CONSERVATIVE_OFFICER(_ctx(stop_loss=None, risk_pct=0.0))
    assert v["verdict"] == "reduce"
    assert v["maxVolume"] == 0.05


def test_conservative_reduces_on_elevated_risk():
    v = CONSERVATIVE_OFFICER(_ctx(risk_pct=2.5))
    assert v["verdict"] == "reduce"
    assert v["maxVolume"] == 0.05


def test_neutral_reduces_at_midpoint():
    v = NEUTRAL_OFFICER(_ctx(risk_pct=3.5))
    assert v["verdict"] == "reduce"
    assert v["maxVolume"] == 0.075


def test_resolve_single_reject_rejects():
    votes = [
        {"stance": "aggressive", "verdict": "approve", "maxVolume": 0.1},
        {"stance": "conservative", "verdict": "reject", "maxVolume": 0.0},
        {"stance": "neutral", "verdict": "approve", "maxVolume": 0.1},
    ]
    out = resolve_debate(votes, 0.1)
    assert out["approved"] is False
    assert out["verdict"] == "reject"
    assert len(out["blockers"]) == 1


def test_resolve_reduce_takes_minimum():
    votes = [
        {"stance": "aggressive", "verdict": "approve", "maxVolume": 0.1},
        {"stance": "conservative", "verdict": "reduce", "maxVolume": 0.05},
        {"stance": "neutral", "verdict": "reduce", "maxVolume": 0.075},
    ]
    out = resolve_debate(votes, 0.1)
    assert out["approved"] is True
    assert out["verdict"] == "reduce"
    assert out["maxVolume"] == 0.05


def test_resolve_all_approve_keeps_requested():
    votes = [
        {"stance": "aggressive", "verdict": "approve", "maxVolume": 0.1},
        {"stance": "conservative", "verdict": "approve", "maxVolume": 0.1},
        {"stance": "neutral", "verdict": "approve", "maxVolume": 0.1},
    ]
    out = resolve_debate(votes, 0.1)
    assert out["approved"] is True
    assert out["verdict"] == "approve"
    assert out["maxVolume"] == 0.1


def test_build_gate_context_zero_equity_is_safe():
    ctx = build_gate_context(
        {"symbol": "XAUUSD", "side": "buy", "volume": 0.1, "price": 4300.0,
         "riskAmount": 5.0, "stopLoss": 4295.0},
        portfolio={"equity": 0},
    )
    assert ctx["notionalPct"] == 0.0
    assert ctx["riskAmountPct"] == 0.0


def test_run_portfolio_gate_persists_and_approves():
    db.collection("risk_debate_history").clear()
    gate = run_portfolio_gate(
        {"symbol": "XAUUSD", "side": "buy", "volume": 0.1, "price": 4300.0,
         "riskAmount": 5.0, "stopLoss": 4295.0, "takeProfit": 4310.0, "confidence": 0.8},
        portfolio={"equity": 10000.0},
    )
    assert gate["approved"] is True
    assert gate["verdict"] == "approve"
    assert gate["maxVolume"] == 0.1
    latest = get_latest_risk_debate("XAUUSD")
    assert latest is not None
    assert latest["verdict"] == "approve"


def test_run_portfolio_gate_rejects_high_risk():
    db.collection("risk_debate_history").clear()
    gate = run_portfolio_gate(
        {"symbol": "XAUUSD", "side": "buy", "volume": 0.1, "price": 4300.0,
         "riskAmount": 600.0, "stopLoss": 4295.0, "takeProfit": 4310.0, "confidence": 0.8},
        portfolio={"equity": 10000.0},
    )
    assert gate["approved"] is False
    assert gate["verdict"] == "reject"


def test_place_order_gate_reject_blocks():
    _reset()
    with mock.patch("app.modules.risk.debate.portfolio_gate.run_portfolio_gate", return_value={
        "approved": False, "verdict": "reject", "maxVolume": 0.0,
        "reason": "risk-debate reject", "blockers": [{"stance": "conservative"}],
        "reduceReasons": [], "officers": [], "record": {"id": "rg-test"},
    }):
        res = trading_engine.place_order({
            "symbol": "XAUUSD", "side": "buy", "volume": 0.1, "price": 4300.0,
            "stopLoss": 4295.0, "takeProfit": 4310.0, "source": "ai-decision",
        })
        assert res["status"] == "rejected"
        assert any("risk-debate" in v for v in res["violations"])


def test_place_order_gate_reduce_shrinks_volume():
    _reset()
    with mock.patch("app.modules.risk.debate.portfolio_gate.run_portfolio_gate", return_value={
        "approved": True, "verdict": "reduce", "maxVolume": 0.05,
        "requestedVolume": 0.1, "reason": "halving", "blockers": [],
        "reduceReasons": [{"stance": "conservative"}], "officers": [],
        "record": {"id": "rg-reduce"},
    }):
        res = trading_engine.place_order({
            "symbol": "XAUUSD", "side": "buy", "volume": 0.1, "price": 4300.0,
            "stopLoss": 4295.0, "takeProfit": 4310.0, "source": "ai-decision",
        })
        assert res["status"] == "filled"
        assert res["order"]["volume"] == 0.05
        assert res["position"]["volume"] == 0.05
        assert res["order"]["riskDebate"]["id"] == "rg-reduce"


def test_gate_fails_open_on_error():
    with mock.patch("app.modules.risk.debate.debate_order", side_effect=RuntimeError("boom")):
        gate = run_portfolio_gate(
            {"symbol": "XAUUSD", "side": "buy", "volume": 0.1, "price": 4300.0,
             "riskAmount": 5.0, "stopLoss": 4295.0},
            portfolio={"equity": 10000.0},
        )
        assert gate["approved"] is True
        assert gate["verdict"] == "approve"


def test_debate_order_produces_three_officer_votes():
    out = debate_order(_ctx())
    assert len(out["officers"]) == 3
    stances = {o["stance"] for o in out["officers"]}
    assert stances == {"aggressive", "conservative", "neutral"}
