"""Regression tests for MT5 adapter init under both event-loop conditions.

Bug: ``init_mt5`` created ``asyncio.create_task(_live_connect_guard())`` where
the coroutine is produced before ``create_task`` can raise ``RuntimeError`` in
the no-running-loop branch, orphaning it ("RuntimeWarning: coroutine
'_live_connect_guard' was never awaited"). The repository read via ``run_sync``
had the same orphaning problem when a loop *was* running.

These tests assert that:
  - no "never awaited" RuntimeWarning is emitted under either condition, and
  - ``_live_connect_guard`` actually executes (state connected) in both cases.
"""
import asyncio
import gc
import os
import sys
import warnings
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test_mt5_init")
os.environ["POSTGRES_ENABLED"] = "false"
os.environ["DATABASE_URL"] = ""

from app.modules.mt5 import adapter  # noqa: E402


async def _fake_connect_live():
    await asyncio.sleep(0)
    adapter.mt5_state.connected = True
    return adapter.mt5_state.to_dict()


async def _fake_get():
    await asyncio.sleep(0)
    return None


def _capture_never_awaited(fn):
    with mock.patch.object(adapter, "_live_mode", return_value=True), mock.patch.object(
        adapter, "connect_live", side_effect=_fake_connect_live
    ), mock.patch(
        "app.persistence.mt5_connection_repository.mt5_connection_repository.get",
        side_effect=_fake_get,
    ), warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        fn()
        gc.collect()
    bad = [str(x.message) for x in w if "never awaited" in str(x.message)]
    return bad


def test_init_mt5_no_loop_no_orphaned_coroutine():
    def run():
        adapter.mt5_state.connected = False
        adapter.init_mt5()

    bad = _capture_never_awaited(run)
    assert bad == [], f"orphaned coroutine warnings: {bad}"
    assert adapter.mt5_state.connected is True, "live connect guard did not run without a running loop"


def test_init_mt5_running_loop_no_orphaned_coroutine():
    async def scenario():
        adapter.mt5_state.connected = False
        with mock.patch.object(adapter, "_live_mode", return_value=True), mock.patch.object(
            adapter, "connect_live", side_effect=_fake_connect_live
        ), mock.patch(
            "app.persistence.mt5_connection_repository.mt5_connection_repository.get",
            side_effect=_fake_get,
        ), warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            adapter.init_mt5()
            await asyncio.sleep(0.05)
            gc.collect()
            bad = [str(x.message) for x in w if "never awaited" in str(x.message)]
            assert bad == [], f"orphaned coroutine warnings: {bad}"
            assert adapter.mt5_state.connected is True, "live connect guard did not run with a running loop"

    asyncio.run(scenario())


def test_init_mt5_demo_mode_calls_simulate():
    with mock.patch.object(adapter, "_live_mode", return_value=False), mock.patch.object(
        adapter, "simulate_connection"
    ) as sim, mock.patch(
        "app.persistence.mt5_connection_repository.mt5_connection_repository.get",
        side_effect=_fake_get,
    ):
        adapter.init_mt5()
    assert sim.called, "demo mode should call simulate_connection()"
