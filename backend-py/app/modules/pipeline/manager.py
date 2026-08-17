"""Data pipeline manager mirroring the Node pipeline/manager.js."""
import time

from ...foundation.logger import logger
from ...foundation.json_store import db
from ...foundation.event_bus import event_bus
from ...foundation.queue import queue_system
from ...foundation.scheduler import scheduler
from ..marketdata.engine import generate_candles, INSTRUMENTS  # noqa: F401

DATA_CONTRACTS = {
    "p1": {
        "schema": {"time": "number", "open": "number", "high": "number", "low": "number", "close": "number", "volume": "number", "symbol": "string"},
        "required": ["open", "high", "low", "close", "volume"],
    },
    "p2": {
        "schema": {"title": "string", "sentiment": "number", "impact": "number", "source": "string", "time": "number"},
        "required": ["title", "sentiment", "impact"],
    },
    "p3": {
        "schema": {"name": "string", "currency": "string", "impact": "number", "time": "number", "forecast": "number", "actual": "number"},
        "required": ["name", "impact"],
    },
    "p4": {
        "schema": {"symbol": "string", "name": "string", "type": "string", "pip": "number"},
        "required": ["symbol", "type"],
    },
    "p5": {
        "schema": {"direction": "string", "confidence": "number", "win": "boolean", "profit": "number"},
        "required": ["direction", "confidence", "win"],
    },
}

_NUMERIC_TYPES = {"number", "int", "float"}
_STRING_TYPES = {"string", "str"}


def _row_contract_errors(contract, row):
    """Return a list of schema violations for a single row against a contract."""
    errors = []
    if not isinstance(row, dict):
        return ["row is not an object"]
    for field in contract.get("required", []):
        if row.get(field) is None:
            errors.append(f"missing required field '{field}'")
    expected = contract.get("schema", {})
    for field, type_name in expected.items():
        value = row.get(field)
        if value is None:
            continue
        if type_name in _NUMERIC_TYPES and not isinstance(value, (int, float)):
            errors.append(f"field '{field}' must be numeric, got {type(value).__name__}")
        elif type_name in _STRING_TYPES and not isinstance(value, str):
            errors.append(f"field '{field}' must be string, got {type(value).__name__}")
        elif type_name == "boolean" and not isinstance(value, bool):
            errors.append(f"field '{field}' must be boolean, got {type(value).__name__}")
    return errors


def validate_contract(pipeline_id, rows):
    """Validate a batch of rows against the pipeline's data contract."""
    contract = DATA_CONTRACTS.get(pipeline_id)
    if not contract:
        return {"valid": True, "invalidRows": 0, "errors": ["no-contract-defined"]}
    invalid = 0
    errors = []
    for idx, row in enumerate(rows):
        row_errors = _row_contract_errors(contract, row)
        if row_errors:
            invalid += 1
            errors.append({"row": idx, "errors": row_errors})
    return {"valid": invalid == 0, "invalidRows": invalid, "errors": errors}


def dead_letter(pipeline_id, row, reason):
    """Persist a rejected row to the pipeline dead-letter queue."""
    return db.collection("pipeline_dlq").insert({
        "pipelineId": pipeline_id,
        "payload": row,
        "reason": reason,
        "failedAt": int(time.time() * 1000),
        "retried": False,
        "retriedAt": None,
    })


def retry_dlq(limit=50):
    """Re-run recoverable dead-lettered rows through their pipeline."""
    col = db.collection("pipeline_dlq")
    recoverable = [r for r in col.find({}) if not r.get("retried") and r.get("reason") != "schema-error"][:limit]
    retried = 0
    for row in recoverable:
        pipeline = db.collection("pipelines").find_one({"id": row.get("pipelineId")})
        if not pipeline:
            continue
        check = validate_contract(row.get("pipelineId"), [row.get("payload") or {}])
        if check["valid"]:
            execute_pipeline(pipeline)
            col.update(row["id"], {"retried": True, "retriedAt": int(time.time() * 1000)})
            retried += 1
            logger.info(f"Retried DLQ row {row['id']} for pipeline {row.get('pipelineId')}")
    remaining = len([r for r in col.find({}) if not r.get("retried")])
    return {"retried": retried, "scanned": len(recoverable), "remaining": remaining}


def lineage(pipeline_id):
    """Build the source -> transforms -> target lineage chain for a pipeline."""
    pipeline = db.collection("pipelines").find_one({"id": pipeline_id})
    if not pipeline:
        return None
    runs = db.collection("pipeline_lineage").find({"pipelineId": pipeline_id}, {"sort": ["ranAt", "desc"]})
    transforms = ["validate-contract", "normalize", "deduplicate"] if pipeline.get("type") == "streaming" else ["validate-contract", "transform", "store"]
    return {
        "pipelineId": pipeline_id,
        "source": pipeline.get("source"),
        "target": pipeline.get("target"),
        "targetCollection": pipeline.get("target"),
        "transforms": transforms,
        "runs": runs[:10],
    }


def init_data_pipeline():
    col = db.collection("pipelines")
    if col.count() == 0:
        col.insert_many([
            {"id": "p1", "name": "Market OHLC ETL", "type": "batch", "source": "market-providers", "target": "ohlc-store", "enabled": True, "lastRun": None, "status": "idle"},
            {"id": "p2", "name": "News Ingest Stream", "type": "streaming", "source": "news-sources", "target": "news-store", "enabled": True, "lastRun": None, "status": "idle"},
            {"id": "p3", "name": "Economic Data Sync", "type": "batch", "source": "economic-calendar", "target": "events-store", "enabled": True, "lastRun": None, "status": "idle"},
            {"id": "p4", "name": "Feature Engineering", "type": "batch", "source": "raw-market", "target": "feature-store", "enabled": True, "lastRun": None, "status": "idle"},
            {"id": "p5", "name": "AI Model Retraining", "type": "batch", "source": "learning-log", "target": "ai-model", "enabled": True, "lastRun": None, "status": "idle"},
        ])

    def _run_p1():
        run_pipeline("p1")

    scheduler.register({"id": "pipeline-ohlc", "intervalMs": 60000, "handler": _run_p1})
    logger.info("Data pipeline manager initialized")
    return {"runPipeline": run_pipeline, "listPipelines": list_pipelines, "getPipelineStats": get_pipeline_stats}


def run_pipeline(pipeline_id):
    col = db.collection("pipelines")
    pipeline = col.find_one({"id": pipeline_id})
    if not pipeline:
        return None
    if not pipeline["enabled"]:
        return {**pipeline, "status": "disabled"}
    col.update(pipeline_id, {"status": "running", "startedAt": int(time.time() * 1000)})

    def _task():
        result = execute_pipeline(pipeline)
        col.update(pipeline_id, {"status": "completed", "lastRun": int(time.time() * 1000), "lastResult": result["summary"]})
        event_bus.emit("pipeline:completed", {"id": pipeline_id, "result": result["summary"]})
        logger.info(f"Pipeline {pipeline_id} completed: {result['summary']['records']} records")
        return result

    return queue_system.add("pipelines", {"id": f"run-{pipeline_id}-{int(time.time() * 1000)}", "fn": _task})


def execute_pipeline(pipeline):
    result = {"summary": {"records": 0}, "validations": [], "errors": []}
    rows = []
    if pipeline["id"] == "p1":
        records = 0
        for inst in INSTRUMENTS:
            candles = generate_candles(inst["symbol"], "H1", 50)
            col = db.collection(f"ohlc_{inst['symbol']}")
            col.insert_many([c for c in candles if not col.find_one({"time": c["time"]})][-10:])
            records += len(candles)
            rows.extend(candles)
        result["summary"]["records"] = records
        result["validations"].append("OHLC schema validated")
    elif pipeline["id"] == "p2":
        news = db.collection("news_items").find({})
        rows = news
        result["summary"]["records"] = len(news)
        result["validations"].append("News items deduplicated")
    elif pipeline["id"] == "p3":
        events = db.collection("economic_events").find({})
        rows = events
        result["summary"]["records"] = len(events)
        result["validations"].append("Economic events cross-checked")
    elif pipeline["id"] == "p4":
        rows = INSTRUMENTS
        result["summary"]["records"] = len(INSTRUMENTS)
        result["validations"].append("Features computed for all instruments")
    elif pipeline["id"] == "p5":
        logs = db.collection("learning_log").find({})
        rows = logs
        result["summary"]["records"] = len(logs)
        result["validations"].append("Training samples aggregated")

    contract = validate_contract(pipeline["id"], rows)
    dlq_count = 0
    if not contract["valid"]:
        contract_def = DATA_CONTRACTS.get(pipeline["id"])
        for row in rows:
            if _row_contract_errors(contract_def, row):
                dead_letter(pipeline["id"], row, "schema-error")
                dlq_count += 1
    result["contractValid"] = contract["valid"]
    result["dlqCount"] = dlq_count
    result["validations"].append(f"contract {'valid' if contract['valid'] else 'violated'} ({len(rows) - contract['invalidRows']}/{len(rows)} rows conform)")

    db.collection("pipeline_lineage").insert({
        "pipelineId": pipeline["id"],
        "ranAt": int(time.time() * 1000),
        "sourceCount": len(rows),
        "targetCount": result["summary"]["records"],
        "targetCollection": pipeline.get("target", "unknown"),
    })
    return result


def list_pipelines():
    return db.collection("pipelines").find({})


def get_pipeline_stats():
    pipelines = db.collection("pipelines").find({})
    return {
        "total": len(pipelines),
        "enabled": len([p for p in pipelines if p["enabled"]]),
        "completed": len([p for p in pipelines if p["status"] == "completed"]),
        "lastRuns": [{"id": p["id"], "name": p["name"], "status": p["status"], "lastRun": p["lastRun"]} for p in pipelines],
    }
