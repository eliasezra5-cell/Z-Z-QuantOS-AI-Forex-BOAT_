#!/usr/bin/env python3
"""Run the critical test suites and persist a go-live gate marker.

The production readiness ``critical-tests`` gate blocks go-live until this
script (typically invoked from CI) records a passing run. Marker is written to
``app/tests/.critical-tests.json`` and mirrored into the ``test_results``
collection when the JSON store is available.

Exit code is 0 when every critical suite passes, 1 otherwise.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

CRITICAL_SUITES = [
    "test_safety_gates.py",
    "test_safety_e2e.py",
    "test_strict_risk_policy.py",
    "test_quality_gates.py",
    "test_phase5_adapters.py",
    "test_risk_analyzers.py",
]

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parent
MARKER = BACKEND_ROOT / "app" / "tests" / ".critical-tests.json"


def main():
    passed = True
    failed_suites = []
    for suite in CRITICAL_SUITES:
        path = BACKEND_ROOT / "app" / "tests" / suite
        if not path.exists():
            failed_suites.append(f"{suite} (missing)")
            passed = False
            continue
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(path), "-q", "--no-header"],
            cwd=str(BACKEND_ROOT),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            failed_suites.append(suite)
            passed = False
            print(result.stdout[-2000:], file=sys.stderr)
            print(result.stderr[-2000:], file=sys.stderr)

    marker = {
        "passed": passed,
        "failedSuites": failed_suites,
        "timestamp": int(time.time() * 1000),
        "suites": CRITICAL_SUITES,
        "generatedBy": "write_critical_test_marker",
    }
    MARKER.write_text(json.dumps(marker, indent=2))

    try:
        sys.path.insert(0, str(BACKEND_ROOT))
        from app.foundation.json_store import db

        db.collection("test_results").insert({**marker, "scope": "critical"})
    except Exception:  # noqa: BLE001 - store optional
        pass

    print(json.dumps(marker, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
