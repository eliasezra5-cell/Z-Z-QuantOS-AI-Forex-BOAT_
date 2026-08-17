import pytest


@pytest.fixture(scope="session", autouse=True)
def _stop_background_monitors():
    """Stop brain-monitor background loops started at app.main import time.

    Importing ``app.main`` (e.g. via test_websocket_hub or test_security_headers)
    starts daemon confidence/kill-switch monitor loops that mutate shared trading
    state during the whole session, which can intermittently interfere with tests
    that manipulate positions. The loops are not needed by any test (tests invoke
    the monitor methods synchronously), so stopping them at session start keeps
    test isolation deterministic.
    """
    try:
        from app.modules.execution.brain_monitor import confidence_monitor, kill_switch_monitor

        confidence_monitor.stop()
        kill_switch_monitor.stop()
    except Exception:
        pass
    yield
