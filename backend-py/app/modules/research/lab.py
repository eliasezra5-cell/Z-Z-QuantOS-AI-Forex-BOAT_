"""Research laboratory mirroring the Node research/lab.js."""
import time

from ...foundation.logger import logger
from ...foundation.json_store import db
from ..backtest.engine import run_backtest, compare_strategies


def init_research_lab():
    logger.info("Research laboratory initialized")
    return {
        "runStrategyBuilder": run_strategy_builder,
        "createExperiment": create_experiment,
        "listExperiments": list_experiments,
        "runNotebook": run_notebook,
    }


def run_strategy_builder(params):
    rules = params.get("rules") or []
    symbol = params.get("symbol") or "EURUSD"
    results = {}
    for rule in rules:
        if not rule.get("strategy"):
            continue
        results[rule.get("name") or rule["strategy"]] = run_backtest({
            "symbol": symbol,
            "strategy": rule["strategy"],
            "timeframe": rule.get("timeframe") or "H1",
            "initialCapital": rule.get("initialCapital") or 100000,
            "riskPerTrade": rule.get("riskPerTrade", 0.02),
        })
    return {"symbol": symbol, "rules": [r.get("name") or r["strategy"] for r in rules], "results": results, "comparison": compare_strategies({"symbol": symbol})}


def create_experiment(params):
    col = db.collection("experiments")
    return col.insert({**params, "status": "running", "createdAt": int(time.time() * 1000), "logs": []})


def list_experiments():
    return db.collection("experiments").find({}, {"sort": ["createdAt", "desc"]})[:100]


def run_notebook(params):
    cells = params.get("cells") or []
    outputs = []
    for cell in cells:
        lang = cell.get("language")
        if lang == "javascript":
            output = f"[sandbox] executed {len(cell.get('code') or '')} chars"
        elif lang == "strategy":
            bt = run_backtest({"symbol": params.get("symbol") or "EURUSD", "strategy": cell.get("code") or "trend-follow"})
            output = bt.get("summary") if bt.get("summary") is not None else "backtest complete"
        else:
            output = f"[sandbox] {lang} notebook cell executed"
        outputs.append({"id": cell.get("id"), "language": lang, "code": cell.get("code"), "output": output, "executedAt": int(time.time() * 1000)})
    return {"notebookId": params.get("id"), "cells": outputs}
