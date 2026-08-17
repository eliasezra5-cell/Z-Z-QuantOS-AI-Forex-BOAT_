"""Unit tests for the added QuantOS AI core modules (Batches 10, 12-17, 19-20).

Run with: python3 -m pytest app/tests/test_core.py -q
(or: pytest in the backend-py directory)
"""
import sys
import os
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_test_data")

from app.modules.marketdata.instrument_specs import instrument_specs  # noqa: E402
from app.modules.risk.deterministic import position_sizer, sltp_calculator, risk_score_engine  # noqa: E402
from app.modules.risk.capital_protection import capital_protection  # noqa: E402
from app.modules.validation.engine import validation_engine  # noqa: E402
from app.modules.execution.modes import trading_modes, TRADING_MODES  # noqa: E402
from app.modules.execution.auto_controller import auto_trade_controller  # noqa: E402
from app.modules.execution.profit_protection import profit_protection  # noqa: E402
from app.modules.execution.thesis import thesis_manager, opposite_news_engine  # noqa: E402
from app.modules.execution.mt5_safety import mt5_safety  # noqa: E402
from app.modules.ai.consensus import dynamic_consensus, custom_agent_registry  # noqa: E402
from app.modules.portfolio.performance import calculate_metrics  # noqa: E402
from app.modules.backtest.advanced import walk_forward, monte_carlo  # noqa: E402


def _reset_modes():
    trading_modes.set_mode("DISABLED", actor="admin", reason="test-reset")
    for sw in list((trading_modes.state.get("kill_switches") or {}).keys()):
        trading_modes.trigger_kill_switch(sw, active=False)


def test_instrument_specs():
    spec = instrument_specs.resolve("XAUUSD")
    assert spec is not None
    assert spec["canonical_symbol"] == "XAUUSD"
    assert spec["pip_size"] == 0.1
    assert spec["contract_size"] == 100
    # broker alias resolution
    assert instrument_specs.resolve("GOLD")["canonical_symbol"] == "XAUUSD"
    # pip math
    assert instrument_specs.pips_between("XAUUSD", 4300, 4305) == 50
    # volume normalization respects min/step
    assert instrument_specs.normalize_volume("XAUUSD", 0.005) == 0.01


def test_position_sizing():
    vol = position_sizer.fixed_percent(100000, 1, 4300, 4295, "XAUUSD")
    # risk = 1000 USD, 5 pips at 0.1 per pip per lot -> 1000/(5*0.1)=2000 lots -> capped 100
    assert vol == 100
    vol2 = position_sizer.size("fixed_amount", {"riskAmount": 100, "entry": 4300, "stop": 4299, "symbol": "XAUUSD"})
    assert vol2 == 100  # 100/(10*0.1)=100 lots
    kelly = position_sizer.kelly_criterion(0.6, 200, 100, 100000)
    assert 0 <= kelly <= 0.25


def test_sltp_chain():
    sl = sltp_calculator.stop_loss("buy", 4300, {"order_block": 4295, "fvg": 4293, "swing": 4290})
    assert sl["source"] == "order_block"
    assert sl["stop"] < 4300
    tp = sltp_calculator.take_profit("buy", 4300, sl["stop"], {"rr": 2, "multi_target": True})
    assert tp["source"] == "multi_target"
    assert len(tp["targets"]) == 3
    # invalid level (above entry for buy) must be skipped -> fall to next
    sl2 = sltp_calculator.stop_loss("buy", 4300, {"order_block": 4310, "fvg": 4295})
    assert sl2["source"] == "fvg"


def test_risk_score_engine():
    low = risk_score_engine.score({"dimensions": {"per_trade": 0.1, "account": 0.1}})
    assert low["verdict"] == "approve"
    high = risk_score_engine.score({"dimensions": {"per_trade": 0.9, "account": 0.9, "spread": 0.9}})
    assert high["verdict"] == "reject"


def test_capital_protection():
    # fresh isolated state
    capital_protection.state["start_equity"] = 100000
    capital_protection.state["peak_equity"] = 100000
    capital_protection.state["shield_level"] = "GREEN"
    capital_protection.state["emergency_stop"] = False
    capital_protection.state["fail_closed"] = []
    capital_protection.state["daily_locked"] = False
    # daily loss of 5% (5000 / 100000) -> RED + emergency stop
    portfolio = {"equity": 100000, "dailyLoss": 5000, "dailyLossLimitPct": 5}
    res = capital_protection.evaluate(portfolio)
    assert res["shield_level"] == "RED"
    assert res["emergency_stop"] is True
    blocked, why = capital_protection.is_blocked()
    assert blocked is True
    # emergency stop cleared explicitly (cannot auto-deactivate)
    capital_protection.deactivate_emergency_stop("admin")
    assert capital_protection.get_status()["emergency_stop"] is False
    # reset for other tests
    capital_protection.state["shield_level"] = "GREEN"
    capital_protection.state["emergency_stop"] = False
    capital_protection._save()


def test_validation_engine():
    ctx = {
        "news": {"verified": True, "sourceTier": 1, "trust": 0.8},
        "technical": {"structureSupported": True, "contradiction": False, "mtfAligned": True},
        "smc": {"executionZone": True, "zoneQuality": 0.7, "mitigated": False},
        "macro": {"weekend": False, "lowLiquidity": False, "conflictingEvents": False},
        "market": {"crossMarketAligned": True, "spreadPips": 1, "maxSpreadPips": 3, "volatilityInRange": True},
        "risk": {"dailyLimitReached": False, "weeklyLimitReached": False, "maxPositionsReached": False, "marginLow": False, "consecutiveLossesReached": False},
    }
    res = validation_engine.evaluate(ctx)
    assert res["can_auto_execute"] is True
    # hard blocker overrides everything
    validation_engine.raise_hard_blocker("stale_market_data", "test")
    ctx["staleMarketData"] = True
    res2 = validation_engine.evaluate(ctx)
    assert res2["hard_blockers"]["blocked"] is True
    assert res2["can_auto_execute"] is False
    validation_engine.clear_hard_blocker("stale_market_data")


def test_trading_modes():
    _reset_modes()
    assert trading_modes.get_mode() == "DISABLED"
    # Admin may switch directly to SEMI_AUTO / AUTO_FULL (no staged promotion
    # required) - this is the intended "cannot-skip-promotion-stage" fix.
    res = trading_modes.set_mode("AUTO_FULL", actor="admin", reason="test")
    assert res.get("status") == "ok"
    assert trading_modes.get_mode() == "AUTO_FULL"
    # ANALYSIS_ONLY is the required first stage for non-admin users
    _reset_modes()
    trading_modes.set_mode("ANALYSIS_ONLY", actor="user", reason="test")
    # AUTO_FULL requires admin
    res = trading_modes.set_mode("AUTO_FULL", actor="user", reason="x")
    assert res.get("status") == "auto-full-requires-admin"
    # non-admin users cannot skip stages (PAPER needs SHADOW first)
    res = trading_modes.set_mode("PAPER", actor="user", reason="test")
    assert res.get("status") == "cannot-skip-promotion-stage"
    # admin may also switch to a specific stage directly
    res = trading_modes.set_mode("SEMI_AUTO", actor="admin", reason="test")
    assert res.get("status") == "ok"
    assert trading_modes.get_mode() == "SEMI_AUTO"
    # kill switch triggers emergency stop
    trading_modes.set_mode("SHADOW", actor="admin", reason="test")
    trading_modes.set_mode("PAPER", actor="admin", reason="test")
    trading_modes.trigger_kill_switch("mt5_disconnected", True, "test")
    assert trading_modes.get_mode() == "EMERGENCY_STOP"
    _reset_modes()


def test_auto_controller():
    _reset_modes()
    # disabled -> no-trade
    verdict, reasons = auto_trade_controller.evaluate({"symbol": "XAUUSD", "confidence": {"score": 0.95}})
    assert verdict == "no-trade"
    assert "auto-trading-disabled" in reasons
    # in AUTO_LIMITED, high confidence + passing validation -> auto-execute
    for m in ("ANALYSIS_ONLY", "SHADOW", "PAPER", "SEMI_AUTO", "AUTO_LIMITED"):
        trading_modes.set_mode(m, actor="admin", reason="test")
    trading_modes.record_observation(confidence_calibrated=True, walk_forward_passed=True, risk_approved=True, admin_approved=True)
    ctx = {
        "news": {"verified": True, "sourceTier": 1, "trust": 0.8},
        "technical": {"structureSupported": True, "contradiction": False, "mtfAligned": True},
        "smc": {"executionZone": True, "zoneQuality": 0.7, "mitigated": False},
        "macro": {"weekend": False, "lowLiquidity": False, "conflictingEvents": False},
        "market": {"crossMarketAligned": True, "spreadPips": 1, "maxSpreadPips": 3, "volatilityInRange": True},
        "risk": {"dailyLimitReached": False, "weeklyLimitReached": False, "maxPositionsReached": False, "marginLow": False, "consecutiveLossesReached": False},
    }
    verdict, _ = auto_trade_controller.evaluate({"symbol": "XAUUSD", "confidence": {"score": 0.95}}, ctx)
    assert verdict == "auto-execute"
    # low confidence -> no-trade
    verdict, _ = auto_trade_controller.evaluate({"symbol": "XAUUSD", "confidence": {"score": 0.5}}, ctx)
    assert verdict == "no-trade"
    _reset_modes()


def test_profit_protection():
    pos = {"id": "p1", "symbol": "XAUUSD", "side": "buy", "entryPrice": 4300, "stopLoss": 4298, "volume": 1.0}
    # break even at +15 pips
    res = profit_protection.break_even(pos, 4302, 20)
    assert res["status"] == "ok"
    assert res["newSl"] >= 4300
    # safety: trailing never backwards
    res = profit_protection.trailing_stop(pos, 4301, atr=1.0)
    assert res["status"] != "ok" or res["newSl"] >= 4298
    # partial close: 20 pips gain vs 20 pips risk (1:1) -> TP1 30%
    res = profit_protection.partial_close(pos, 5, 4300, 4302)
    assert res["status"] == "ok"
    assert res["tag"] == "TP1"
    assert abs(res["percent"] - 0.3) < 1e-9


def test_thesis_and_opposite_news():
    from app.foundation.json_store import db
    db.collection("trade_theses").clear()
    db.collection("opposite_news_actions").clear()
    thesis = thesis_manager.create_thesis("pos-x", {
        "direction": "buy",
        "supportingNewsIds": ["n1"],
        "invalidationConditions": [{"price": 4250, "side": "below"}],
    })
    assert thesis["thesis_version"] == 1
    v2 = thesis_manager.new_version("pos-x", {"direction": "buy", "contradictingNewsIds": ["n2"]}, "opposite-news")
    assert v2["thesis_version"] == 2
    assert "n2" in v2["contradicting_news_ids"]
    assert thesis_manager.invalidation_violated("pos-x", 4240) is True
    # opposite news action
    action = opposite_news_engine.evaluate(
        {"id": "pos-x", "symbol": "XAUUSD", "profit": 100},
        {"relevant": True, "contradictionSeverity": 0.95, "sourceAuthority": 0.8, "confirmationCount": 3, "persistenceSeconds": 700},
        thesis,
        {"pnlPct": 0.3, "spreadOk": True, "liquidityOk": True},
    )
    assert action["action"] in ("REVERSE", "CLOSE")


def test_mt5_safety():
    envelope = mt5_safety.build_order({"symbol": "XAUUSD", "side": "buy"}, {"decision_id": "d1"})
    assert envelope["idempotency_key"]
    assert envelope["correlation_id"]
    dup = mt5_safety.duplicate_check(envelope)
    assert dup["duplicate"] is False
    mt5_safety.record(envelope, "submitted")
    dup2 = mt5_safety.duplicate_check(envelope)
    assert dup2["duplicate"] is True
    # freeze blocks execution
    mt5_safety.freeze_symbol("XAUUSD", "test")
    assert mt5_safety.is_frozen("XAUUSD") is True
    mt5_safety.unfreeze_symbol("XAUUSD")
    assert mt5_safety.is_frozen("XAUUSD") is False
    # reconciliation mismatch freezes
    mismatches = mt5_safety.reconcile(
        [{"id": "L1", "symbol": "XAUUSD", "status": "open", "stopLoss": 4298, "takeProfit": 4310}],
        [{"id": "L2", "symbol": "XAUUSD", "stopLoss": 4290, "takeProfit": 4310}],
    )
    assert len(mismatches) >= 1


def test_consensus_abstention():
    votes = [
        {"agent_id": "news", "direction": "buy", "confidence": 0.9, "abstention": "TRADE"},
        {"agent_id": "market", "direction": "buy", "confidence": 0.8, "abstention": "TRADE"},
        {"agent_id": "risk", "direction": "neutral", "confidence": 0.8, "abstention": "NO_TRADE"},
    ]
    res = dynamic_consensus.compute(votes)
    assert res["direction"] == "buy"
    # veto: any agent NO_TRADE with conf > 0.8 -> overall no_trade
    votes2 = [
        {"agent_id": "news", "direction": "buy", "confidence": 0.95, "abstention": "TRADE"},
        {"agent_id": "market", "direction": "sell", "confidence": 0.9, "abstention": "NO_TRADE"},
    ]
    res2 = dynamic_consensus.compute(votes2)
    assert res2["direction"] == "no_trade"
    assert res2["no_trade_veto"] is True


def test_custom_agents():
    row = custom_agent_registry.create({"name": "Test Agent", "voting_weight": 0.1, "system_prompt": "x"})
    assert row["voting_weight"] == 0.1
    bad = custom_agent_registry.create({"name": "Bad", "voting_weight": 0.5})
    assert bad["status"] == "weight-must-be-0-to-20pct"
    custom_agent_registry.remove(row["id"])
    assert all(a["id"] != row["id"] for a in custom_agent_registry.list())


def test_performance_metrics():
    trades = [
        {"profit": 100}, {"profit": -50}, {"profit": 200}, {"profit": -25}, {"profit": 75},
    ]
    equity = [{"value": 100000 + i * 20} for i in range(20)]
    m = calculate_metrics(trades, equity, 100000)
    assert m["total_trades"] == 5
    assert m["win_rate"] == 0.6
    assert m["profit_factor"] > 1
    assert m["expectancy"] == 60.0


def test_backtest_advanced():
    params = {"symbol": "XAUUSD", "strategy": "trend-follow", "candles": 400}
    wf = walk_forward(params)
    assert "verdict" in wf
    assert len(wf["windows"]) == 4
    base = {"trades": [{"profit": 50}, {"profit": -30}, {"profit": 120}, {"profit": -10}], "initialCapital": 100000}
    mc = monte_carlo(base, simulations=200)
    assert "probability_of_ruin" in mc
    assert mc["simulations"] == 200


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(1 if failures else 0)
