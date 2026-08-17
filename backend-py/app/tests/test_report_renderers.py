"""Unit tests for additive report renderers (Batch 25)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_ai_test")

from app.foundation.json_store import JsonStore  # noqa: E402
from app.modules.reports.renderers import (  # noqa: E402
    export_to_file,
    render_report,
    to_excel_csv,
    to_html,
    to_markdown,
)


def _store_with_report():
    store = JsonStore(data_dir=f"/tmp/quantos_render_test_{os.getpid()}")
    report = {
        "id": "rep-1",
        "type": "daily",
        "generatedAt": 1700000000000,
        "portfolio": {"balance": 10000, "equity": 10500, "pnl": 500, "trades": 12, "winRate": 0.6},
        "summary": {"headline": "Portfolio gained 500 in the daily period"},
    }
    store.collection("reports").insert({"id": "rep-1", "generatedAt": 1700000000000, "report": report})
    return store


def test_to_markdown_contains_fields():
    store = _store_with_report()
    md = render_report("rep-1", "markdown", store=store)
    assert "# QuantOS AI Report" in md
    assert "Balance" in md
    assert "Win Rate" in md


def test_to_html_valid():
    store = _store_with_report()
    html = render_report("rep-1", "html", store=store)
    assert "<!DOCTYPE html>" in html
    assert "<table>" in html
    assert "QuantOS" in html


def test_to_excel_csv_has_bom_and_rows():
    store = _store_with_report()
    csv_text = render_report("rep-1", "excel", store=store)
    assert csv_text.startswith("\ufeff")
    assert "Field,Value" in csv_text
    assert "portfolio.pnl" in csv_text


def test_render_unknown_report_returns_none():
    store = _store_with_report()
    assert render_report("missing", "markdown", store=store) is None


def test_render_default_json_fallback():
    store = _store_with_report()
    out = render_report("rep-1", "unknown-fmt", store=store)
    assert '"type": "daily"' in out


def test_export_to_file_writes():
    store = _store_with_report()
    path = export_to_file("rep-1", "markdown", store=store)
    assert path and os.path.exists(path)
    with open(path, "r", encoding="utf-8") as fh:
        assert "QuantOS AI Report" in fh.read()
