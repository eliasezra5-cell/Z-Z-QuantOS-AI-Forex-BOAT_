"""Tests for the additive execution extensions.

Covers the repository-backed position sync (auto-close below the 70%
confidence gate on opposite-direction news), the autonomous news autopilot
scheduler job, and the institutional execution engine (float-confidence
bridge -> MT5 market order / suggested trade / NO_TRADE gates, Decimal lot
sizing with NO FLOATS).
"""
import asyncio
import os
import sys
import time
from unittest import mock
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test_exec")
os.environ["POSTGRES_ENABLED"] = "false"
os.environ["DATABASE_URL"] = ""
os.environ.setdefault("CRYPTO_KEY", "quantos-test-crypto-key-0001")

from app.modules.execution.position_sync import position_sync, RepositoryPositionSync  # noqa: E402
from app.modules.news import autopilot  # noqa: E402
from app.modules.execution import institutional_executor as inst  # noqa: E402
from app.modules.execution.institutional_executor import InstitutionalExecutor  # noqa: E402
from app.modules.execution.auto_controller import auto_trade_controller  # noqa: E402
from app.modules.execution.modes import trading_modes  # noqa: E402


def _open_position(pos_id="pos-ext-test", side="buy", confidence=0.95):
    return {
        "id": pos_id,
        "symbol": "XAUUSD",
        "side": side,
        "lotSize": 0.1,
        "entry": 2400.0,
        "status": "open",
        "initialConfidence": confidence,
        "openedAt": 1700000000000,
    }


def _close_position(position):
    import time

    return {**position, "status": "closed", "closedAt": int(time.time() * 1000)}


def _decision(symbol="XAUUSD", direction="sell", confidence=0.65, status="SUGGESTED"):
    return {
        "id": "decision-ext-test",
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "status": status,
        "newsIds": [],
    }


def _suggested(symbol="XAUUSD", side="buy", confidence=0.80, trade_id="sug-test"):
    decision = {
        "id": f"dec-{trade_id}",
        "symbol": symbol,
        "recommendation": {"direction": side},
        "confidence": {"score": confidence},
        "xai": {"rationale": "test rationale"},
    }
    return auto_trade_controller.create_suggested_trade(decision, expiry_seconds=3600)


# --------------------------------------------------------------------------- #
# RepositoryPositionSync
# --------------------------------------------------------------------------- #
class TestRepositoryPositionSync:
    def test_upsert_and_list_open_positions(self):
        position = _open_position()
        try:
            saved = position_sync.upsert_position(position)
            assert saved["id"] == "pos-ext-test"
            assert saved["status"] == "open"
            open_rows = position_sync.list_open_positions()
            assert any(r["id"] == "pos-ext-test" for r in open_rows)
        finally:
            position_sync.upsert_position(_close_position(position))

    def test_sync_from_mt5_persists_snapshots(self):
        snapshots = [
            {"mt5Ticket": 1, "symbol": "EURUSD", "side": "buy", "entryPrice": 1.10, "volume": 0.1},
            {"mt5Ticket": 2, "symbol": "GBPUSD", "side": "sell", "entryPrice": 1.25, "volume": 0.2},
        ]
        synced = position_sync.sync_from_mt5(snapshots)
        assert len(synced) == 2
        assert {s["id"] for s in synced} == {1, 2}
        for s in synced:
            position_sync.upsert_position(_close_position(s))

    def test_auto_close_below_70_on_opposite_news(self):
        position = _open_position(pos_id="pos-ext-close", side="buy", confidence=0.90)
        position_sync.upsert_position(position)
        try:
            with mock.patch.object(
                auto_trade_controller, "evaluate_open_trade",
                return_value={"action": "auto-close", "reason": "Confidence degradation below 70%"},
            ):
                actions = position_sync.evaluate_open_positions(
                    decision=_decision(direction="sell", confidence=0.60)
                )
            assert len(actions) == 1
            assert actions[0]["position_id"] == "pos-ext-close"
            assert actions[0]["action"] == "auto-close"
            open_rows = position_sync.list_open_positions()
            assert not any(r["id"] == "pos-ext-close" for r in open_rows)
        finally:
            position_sync.upsert_position(_close_position(position))

    def test_no_close_when_confidence_above_gate(self):
        position = _open_position(pos_id="pos-ext-hold", side="buy", confidence=0.90)
        position_sync.upsert_position(position)
        try:
            actions = position_sync.evaluate_open_positions(
                decision=_decision(direction="sell", confidence=0.80)
            )
            assert actions == []
            open_rows = position_sync.list_open_positions()
            assert any(r["id"] == "pos-ext-hold" for r in open_rows)
        finally:
            position_sync.upsert_position(_close_position(position))

    def test_no_close_on_same_direction(self):
        position = _open_position(pos_id="pos-ext-same", side="buy", confidence=0.90)
        position_sync.upsert_position(position)
        try:
            actions = position_sync.evaluate_open_positions(
                decision=_decision(direction="buy", confidence=0.40)
            )
            assert actions == []
        finally:
            position_sync.upsert_position(_close_position(position))

    def test_opposite_news_close_action(self):
        position = _open_position(pos_id="pos-ext-news", side="buy", confidence=0.90)
        position_sync.upsert_position(position)
        from app.modules.execution.thesis import thesis_manager, opposite_news_engine

        try:
            thesis_manager.create_thesis(position["id"], {"direction": "buy"})
            news = {
                "relevant": True,
                "contradictionSeverity": 0.9,
                "confirmationCount": 2,
                "persistenceSeconds": 900,
            }
            with mock.patch.object(
                opposite_news_engine, "evaluate",
                return_value={"action": "CLOSE", "reason": "opposite-news"},
            ):
                actions = position_sync.evaluate_open_positions(news=news)
            assert len(actions) == 1
            assert actions[0]["action"] == "CLOSE"
            open_rows = position_sync.list_open_positions()
            assert not any(r["id"] == "pos-ext-news" for r in open_rows)
        finally:
            position_sync.upsert_position(_close_position(position))


# --------------------------------------------------------------------------- #
# News autopilot
# --------------------------------------------------------------------------- #
class TestNewsAutopilot:
    def test_init_news_autopilot_registers_job(self):
        job_id = autopilot.init_news_autopilot()
        try:
            assert job_id == autopilot.JOB_ID
            assert autopilot.JOB_ID in autopilot.scheduler.jobs
            job = autopilot.scheduler.jobs[autopilot.JOB_ID]
            assert job["intervalMs"] >= 10 * 1000
        finally:
            autopilot.scheduler.disable(autopilot.JOB_ID)
            autopilot.scheduler.jobs.pop(autopilot.JOB_ID, None)

    def test_init_news_autopilot_is_idempotent(self):
        job_id = autopilot.init_news_autopilot()
        second = autopilot.init_news_autopilot()
        try:
            assert job_id == second == autopilot.JOB_ID
            assert list(autopilot.scheduler.jobs).count(autopilot.JOB_ID) == 1
        finally:
            autopilot.scheduler.disable(autopilot.JOB_ID)
            autopilot.scheduler.jobs.pop(autopilot.JOB_ID, None)

    def test_run_poll_calls_poll_news_sync(self):
        with mock.patch.object(autopilot, "poll_news_sync", return_value={"collected": 3}) as poll:
            result = autopilot._run_poll()
        poll.assert_called_once_with(autopilot.DEFAULT_LIMIT_PER_SOURCE)
        assert result == {"collected": 3}


# --------------------------------------------------------------------------- #
# InstitutionalExecutor
# --------------------------------------------------------------------------- #
class TestInstitutionalExecutor:
    def test_is_new_pipeline_detects_float_confidence(self):
        executor = InstitutionalExecutor()
        assert executor._is_new_pipeline(_decision(confidence=0.80)) is True
        assert executor._is_new_pipeline({"confidence": {"score": 0.80}}) is False
        assert executor._is_new_pipeline({}) is False

    def test_handle_skips_legacy_format(self):
        executor = InstitutionalExecutor()
        result = executor.handle({"symbol": "XAUUSD", "confidence": {"score": 0.9}})
        assert result["status"] == "skipped"
        assert result["reason"] == "legacy-format"

    def test_handle_skips_no_trade(self):
        executor = InstitutionalExecutor()
        result = executor.handle(_decision(status="NO_TRADE", confidence=0.60))
        assert result["status"] == "skipped"
        assert result["reason"] == "NO_TRADE"

    def test_handle_skips_risk_rejected(self):
        executor = InstitutionalExecutor()
        result = executor.handle({**_decision(status="AUTO_EXECUTE", confidence=0.95), "riskApproved": False})
        assert result["status"] == "skipped"

    def test_handle_skips_without_direction(self):
        executor = InstitutionalExecutor()
        result = executor.handle({**_decision(status="AUTO_EXECUTE", confidence=0.95), "direction": "hold"})
        assert result["status"] == "skipped"
        assert result["reason"] == "no-direction"

    def test_handle_suggested_records_suggestion(self):
        executor = InstitutionalExecutor()
        with mock.patch.object(auto_trade_controller, "create_suggested_trade", return_value={"id": "sug-1"}) as create:
            result = executor.handle(_decision(status="SUGGESTED", confidence=0.80))
        create.assert_called_once()
        assert result["status"] == "suggested"
        assert result["suggested"]["id"] == "sug-1"

    def test_handle_auto_execute_with_mode_off_degrades_to_suggestion(self):
        executor = InstitutionalExecutor()
        original_mode = trading_modes.get_mode()
        try:
            with mock.patch.object(trading_modes, "get_mode", return_value="DISABLED"):
                with mock.patch.object(auto_trade_controller, "create_suggested_trade", return_value={"id": "sug-2"}):
                    result = executor.handle(
                        {**_decision(status="AUTO_EXECUTE", confidence=0.95, direction="buy"),
                         "entry": 2400.0, "stopLoss": 2395.0, "takeProfit": 2410.0}
                    )
            assert result["status"] == "suggested"
            assert "auto-mode-off" in result["reason"]
        finally:
            trading_modes.set_mode(original_mode)

    def test_handle_auto_execute_places_market_order(self):
        executor = InstitutionalExecutor()
        try:
            with mock.patch.object(trading_modes, "get_mode", return_value="AUTO_FULL"):
                with mock.patch.object(inst, "_place_order", new=AsyncMock(return_value={"ticket": 777})):
                    with mock.patch.object(inst.portfolio_service, "get", return_value={"equity": 10000}):
                        result = executor.handle(
                            {**_decision(status="AUTO_EXECUTE", confidence=0.95, direction="buy"),
                             "entry": 2400.0, "stopLoss": 2395.0, "takeProfit": 2410.0}
                        )
            assert result["status"] == "placed"
            assert result["order"]["type"] == "market"
            assert result["order"]["side"] == "buy"
            assert result["order"]["comment"] == "institutional-ai"
            assert result["position"]["status"] == "open"
            assert result["position"]["mt5Ticket"] == 777
        finally:
            open_positions = position_sync.list_open_positions()
            for pos in open_positions:
                if pos.get("mt5Ticket") == 777 or pos.get("symbol") == "XAUUSD":
                    position_sync.upsert_position(_close_position(pos))

    def test_lot_size_is_decimal_no_floats(self):
        from decimal import Decimal

        executor = InstitutionalExecutor()
        with mock.patch.object(inst.portfolio_service, "get", return_value={"equity": 10000}):
            lot = executor._lot_size(_decision(direction="buy"), Decimal("2400"), Decimal("2395"))
        assert isinstance(lot, Decimal)
        assert lot == lot.quantize(Decimal("0.01"))
        assert lot >= Decimal("0.01")

    def test_fallback_stop_generates_level(self):
        from decimal import Decimal

        executor = InstitutionalExecutor()
        stop = executor._fallback_stop("XAUUSD", "buy", Decimal("2400"))
        assert stop is not None
        assert stop < Decimal("2400")


# --------------------------------------------------------------------------- #
# Telegram /approve -> real approval path + execution trigger
# --------------------------------------------------------------------------- #
class TestTelegramApprove:
    def _bot(self):
        from app.modules.integrations.telegram_bot import telegram_bot

        return telegram_bot

    def test_approve_marks_suggestion_accepted(self):
        sug = _suggested(trade_id="sug-tg-1")
        reply = self._bot()._cmd_approve([sug["id"]])
        assert "Approved suggestion" in reply
        saved = auto_trade_controller.col.find_one({"id": sug["id"]})
        assert saved["status"] == "accepted"
        assert saved.get("approved") is None
        assert saved.get("approvedBy") is None

    def test_approve_emits_suggested_trade_approved(self):
        from app.foundation.event_bus import event_bus

        sug = _suggested(trade_id="sug-tg-2")
        seen = []
        off = event_bus.on("suggested:trade-approved", lambda e: seen.append(e.get("payload") or e))
        try:
            self._bot()._cmd_approve([sug["id"]])
        finally:
            off()
        assert seen and seen[0].get("trade_id") == sug["id"]

    def test_approve_does_not_emit_legacy_event(self):
        from app.foundation.event_bus import event_bus

        sug = _suggested(trade_id="sug-tg-3")
        seen = []
        off = event_bus.on("telegram:trade-approved", lambda e: seen.append(e))
        try:
            self._bot()._cmd_approve([sug["id"]])
        finally:
            off()
        assert seen == []

    def test_approve_already_accepted_message(self):
        sug = _suggested(trade_id="sug-tg-4")
        auto_trade_controller.approve_suggested(sug["id"])
        reply = self._bot()._cmd_approve([sug["id"]])
        assert "already accepted" in reply

    def test_approve_unknown_id(self):
        reply = self._bot()._cmd_approve(["no-such-suggestion"])
        assert "No suggested trade" in reply

    def test_approve_usage_when_no_params(self):
        reply = self._bot()._cmd_approve([])
        assert "Usage: /approve" in reply


class TestSuggestedTradeExecutionTrigger:
    def test_approved_suggestion_reaches_risk_gated_execution(self):
        from app.foundation.event_bus import event_bus
        from app.modules.execution.position_sync import init_position_sync
        from app.modules.trading.engine import trading_engine

        init_position_sync()
        sug = _suggested(trade_id="sug-exec-1")
        with mock.patch.object(
            trading_engine, "place_order", return_value={"status": "filled", "order": {"id": "ord-1"}}
        ) as place:
            auto_trade_controller.approve_suggested(sug["id"])
            deadline = time.time() + 3
            while not place.called and time.time() < deadline:
                time.sleep(0.02)
        assert place.called
        order = place.call_args[0][0]
        assert order["symbol"] == "XAUUSD"
        assert order["side"] == "buy"
        assert order["source"] == "ai-decision"
        saved = auto_trade_controller.col.find_one({"id": sug["id"]})
        assert saved["status"] == "executed"
        assert saved["orderId"] == "ord-1"

    def test_rejected_execution_recorded_on_suggestion(self):
        from app.foundation.event_bus import event_bus
        from app.modules.execution.position_sync import init_position_sync
        from app.modules.trading.engine import trading_engine

        init_position_sync()
        sug = _suggested(trade_id="sug-exec-2")
        with mock.patch.object(
            trading_engine, "place_order",
            return_value={"status": "rejected", "violations": ["stale-market-data"]},
        ) as place:
            auto_trade_controller.approve_suggested(sug["id"])
            deadline = time.time() + 3
            while not place.called and time.time() < deadline:
                time.sleep(0.02)
        saved = auto_trade_controller.col.find_one({"id": sug["id"]})
        assert saved["executionStatus"] == "rejected"
        assert saved["rejectReason"] == "stale-market-data"
        assert saved["status"] == "accepted"
