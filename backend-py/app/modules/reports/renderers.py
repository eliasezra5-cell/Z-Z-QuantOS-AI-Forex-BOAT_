"""Report Renderers (Batch 25, additive).

Adds Markdown and HTML(print-ready/PDF) and Excel-compatible (CSV with BOM +
UTF-8) renderers for the existing report service. ``reports/service.py`` is
left untouched; callers opt-in via ``render_report``.

PDF is emitted as print-optimized HTML that browsers can save as PDF; no
external PDF library dependency is required (keeps the project dependency-free).
"""
import csv
import io
import json
import os
from datetime import datetime, timezone

from ...foundation.logger import logger

EXPORT_DIR = os.environ.get("REPORT_EXPORT_DIR", "/tmp/quantos_reports")


def _fmt_ts(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _money(v):
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def _kv_lines(report):
    p = report.get("portfolio", {})
    return [
        ("Type", str(report.get("type"))),
        ("Generated", _fmt_ts(report.get("generatedAt", 0))),
        ("Balance", _money(p.get("balance"))),
        ("Equity", _money(p.get("equity"))),
        ("PnL", _money(p.get("pnl"))),
        ("Trades", str(p.get("trades"))),
        ("Win Rate", f"{p.get('winRate', 0) * 100:.1f}%"),
    ]


def to_markdown(report):
    lines = [f"# QuantOS AI Report - {report.get('type', 'unknown')}", ""]
    for k, v in _kv_lines(report):
        lines.append(f"- **{k}:** {v}")
    lines.append("")
    summary = report.get("summary") or {}
    lines.append("## Summary")
    lines.append(f"> {summary.get('headline', '')}")
    lines.append("")
    return "\n".join(lines)


def to_html(report):
    rows = "\n".join(
        f"<tr><td><strong>{k}</strong></td><td>{v}</td></tr>" for k, v in _kv_lines(report)
    )
    summary = report.get("summary") or {}
    headline = summary.get("headline", "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>QuantOS AI Report - {report.get('type', '')}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 40px; color: #0f172a; }}
  h1 {{ color: #0f766e; border-bottom: 2px solid #0f766e; padding-bottom: 8px; }}
  table {{ border-collapse: collapse; margin: 20px 0; }}
  td, th {{ border: 1px solid #cbd5e1; padding: 8px 16px; }}
  blockquote {{ background: #f0fdfa; border-left: 4px solid #0f766e; margin: 0; padding: 8px 16px; }}
  @media print {{ body {{ margin: 0; }} }}
</style>
</head>
<body>
<h1>QuantOS AI Report - {report.get('type', 'unknown')}</h1>
<table>{rows}</table>
<blockquote>{headline}</blockquote>
</body>
</html>
"""


def to_excel_csv(report):
    """Excel-friendly CSV (UTF-8 BOM so Excel renders headers correctly)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Field", "Value"])
    for k, v in _kv_lines(report):
        writer.writerow([k, v])
    summary = report.get("summary") or {}
    writer.writerow(["Summary", summary.get("headline", "")])
    p = report.get("portfolio", {})
    for key in ("balance", "equity", "pnl", "trades", "winRate"):
        writer.writerow([f"portfolio.{key}", p.get(key)])
    return "\ufeff" + buf.getvalue()


def render_report(report_id, fmt="markdown", store=None):
    """Render a stored report into markdown / html / excel (CSV+BOM).

    ``store`` is injectable for tests (avoids shared DB pollution).
    """
    from ...foundation.json_store import db as _default_db

    db = store or _default_db
    row = db.collection("reports").find_one({"id": report_id})
    if not row:
        return None
    report = row["report"]
    if fmt == "markdown":
        return to_markdown(report)
    if fmt == "md":
        return to_markdown(report)
    if fmt == "html":
        return to_html(report)
    if fmt in ("excel", "xlsx", "csv"):
        return to_excel_csv(report)
    return json.dumps(report, indent=2)


def export_to_file(report_id, fmt="markdown", store=None):
    """Write the rendered report to ``EXPORT_DIR`` and return the file path."""
    content = render_report(report_id, fmt, store=store)
    if content is None:
        return None
    os.makedirs(EXPORT_DIR, exist_ok=True)
    ext = {"markdown": "md", "md": "md", "html": "html", "excel": "csv", "xlsx": "csv", "csv": "csv"}.get(fmt, "json")
    path = os.path.join(EXPORT_DIR, f"{report_id}.{ext}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


def init_report_renderers():
    os.makedirs(EXPORT_DIR, exist_ok=True)
    logger.info(f"Report renderers (MD/HTML/Excel) initialized -> {EXPORT_DIR}")
    return render_report
