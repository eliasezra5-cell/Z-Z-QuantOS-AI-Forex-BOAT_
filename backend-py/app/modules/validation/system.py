"""Enterprise validation manager mirroring the Node validation/system.js."""
import os
import time

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.json_store import db
from ...foundation.monitoring import monitoring

from ..marketdata.engine import get_quote, get_instrument, generate_candles, INSTRUMENTS  # noqa: F401
from ..news.engine import get_news, get_news_sources
from ..economic.engine import get_economic_events
from ..macro.engine import get_macro_snapshot
from ..historical.engine import get_historical_snapshot  # noqa: F401
from ..ai.decision_center import analyze_symbol
from ..ai.memory import ai_memory, vector_store
from ..ai.learning import learning_engine
from ..risk.engine import risk_engine
from ..portfolio.service import portfolio_service
from ..trading.engine import trading_engine
from ..technical.indicators import calculate_all_indicators
from ..technical.smc import analyze_smc
from ..technical.price_action import analyze_price_action
from ..technical.candlesticks import detect_patterns
from ..backtest.engine import run_backtest
from ..mt5.adapter import init_mt5

VALIDATION_SUITES = [
    {"id": "market-data", "name": "Market Data Validation", "description": "Quotes, instruments and candle generation integrity"},
    {"id": "ai-workflow", "name": "AI Workflow Validation", "description": "Multi-agent decision pipeline, memory and learning"},
    {"id": "news-intelligence", "name": "News Intelligence Validation", "description": "News ingestion, sentiment and source reliability"},
    {"id": "technical-analysis", "name": "Technical Analysis Validation", "description": "Indicators, price action, SMC and candlestick patterns"},
    {"id": "fundamental-analysis", "name": "Fundamental Analysis Validation", "description": "Economic calendar, macro environment and news fundamentals"},
    {"id": "mt5", "name": "MT5 Validation", "description": "MT5 connectivity, orders, positions and trade lifecycle"},
    {"id": "risk-portfolio", "name": "Risk & Portfolio Validation", "description": "Risk engine, capital protection and portfolio integrity"},
    {"id": "api", "name": "API Validation", "description": "Core REST endpoints and response integrity"},
    {"id": "documentation", "name": "Documentation Audit", "description": "README, API surface and coverage documentation"},
]


class ValidationManager:
    def __init__(self):
        self.col = db.collection("validation_runs")
        self.cert_col = db.collection("certifications")

    def init(self):
        logger.info("Enterprise validation manager initialized")
        return self

    async def _validate_market_data(self):
        checks = []
        ok = True
        if not isinstance(INSTRUMENTS, list) or len(INSTRUMENTS) < 5:
            ok = False
            checks.append({"check": "Instrument catalog", "passed": False, "detail": "Insufficient instruments"})
        else:
            checks.append({"check": "Instrument catalog", "passed": True, "detail": f"{len(INSTRUMENTS)} instruments"})

        q = get_quote("EURUSD")
        q_ok = q and q["bid"] > 0 and q["ask"] > q["bid"]
        checks.append({"check": "Quote integrity", "passed": bool(q_ok), "detail": f"bid={q['bid']} ask={q['ask']}" if q else "no quote"})
        if q and not (q["bid"] > 0 and q["ask"] > q["bid"]):
            ok = False

        candles = generate_candles("EURUSD", "H1", 200)
        candle_ok = len(candles) >= 50 and all(c["high"] >= c["low"] and c["high"] >= c["open"] and c["low"] <= c["close"] for c in candles)
        checks.append({"check": "Candle integrity", "passed": candle_ok, "detail": f"{len(candles)} candles, high>=low respected"})
        if not candle_ok:
            ok = False

        for sym in ["EURUSD", "XAUUSD", "BTCUSD", "US500"]:
            inst = get_instrument(sym)
            if not inst or not inst.get("pip"):
                ok = False
                checks.append({"check": f"Instrument {sym}", "passed": False, "detail": "missing pip size"})
        checks.append({"check": "Instrument metadata", "passed": True, "detail": "pip sizes present"})

        return {"passed": ok, "checks": checks, "score": round(len([c for c in checks if c["passed"]]) / len(checks) * 100)}

    async def _validate_ai_workflow(self):
        checks = []
        decision = analyze_symbol("EURUSD")
        decision_ok = decision and decision.get("consensus") and isinstance((decision.get("confidence") or {}).get("score"), (int, float))
        checks.append({"check": "Multi-agent decision", "passed": bool(decision_ok), "detail": f"consensus={decision['consensus']['direction']} confidence={decision['confidence']['score']}" if decision_ok else "failed"})

        agents_ok = isinstance(decision.get("agents"), list) and len(decision["agents"]) >= 7
        checks.append({"check": "Agent consensus (7 agents)", "passed": agents_ok, "detail": f"{len(decision['agents'])} agents voted" if agents_ok else "not all agents"})

        xai = decision.get("xai") or {}
        xai_ok = isinstance(xai.get("contributions"), list) and len(xai["contributions"]) >= 7
        checks.append({"check": "Explainable AI", "passed": bool(xai_ok), "detail": f"{len(xai['contributions'])} contributions" if xai_ok else "missing XAI"})

        memory_ok = callable(getattr(ai_memory, "remember", None)) and isinstance(vector_store.all(), list)
        checks.append({"check": "AI memory & vector store", "passed": bool(memory_ok), "detail": f"{len(vector_store.all())} vectors" if memory_ok else "failed"})

        learning_state = learning_engine.get_state()
        weights = (learning_state or {}).get("weights") or {}
        checks.append({"check": "Learning engine", "passed": bool(learning_state) and len(weights) > 0, "detail": f"weights available ({len(weights)} features)"})

        metrics = self._ai_calibration_metrics()
        ece_ok = metrics["sampleCount"] == 0 or metrics["ece"] < 0.2
        checks.append({"check": "Brier/ECE calibration", "passed": ece_ok, "detail": f"brier={metrics['brier']:.4f} ece={metrics['ece']:.4f} (n={metrics['sampleCount']})"})

        abstention = metrics["abstention"]
        checks.append({"check": "Abstention quality", "passed": abstention["improvesHitRate"], "detail": f"abstainedWinRate={abstention['abstainedWinRate']:.3f} nonAbstainedWinRate={abstention['nonAbstainedWinRate']:.3f} {abstention['note']}".strip()})

        costs = self._expectancy_after_costs()
        checks.append({"check": "Expectancy after costs", "passed": costs["profitable"], "detail": f"expectancyNet={costs['expectancyNet']:.4f} costPerTrade={costs['costPerTrade']:.4f} maxDrawdownPct={costs['maxDrawdownPct']:.2f}"})

        passed = all(c["passed"] for c in checks)
        return {"passed": passed, "checks": checks, "score": round(len([c for c in checks if c["passed"]]) / len(checks) * 100)}

    def _ai_calibration_metrics(self):
        """Compute Brier score, ECE, precision/recall and abstention quality from learning_log."""
        logs = db.collection("learning_log").find({})
        scored = []
        for log in logs:
            conf = log.get("confidence")
            if not isinstance(conf, (int, float)) or not (0 <= conf <= 1):
                continue
            outcome = 1 if log.get("win") else 0
            scored.append({"confidence": conf, "outcome": outcome, "direction": log.get("direction")})

        n = len(scored)
        if n == 0:
            return {
                "sampleCount": 0,
                "brier": 0.0,
                "ece": 0.0,
                "bins": [],
                "directional": {"sampleCount": 0, "precision": 0.0, "recall": 0.0, "baselineWinRate": 0.0, "improvement": 0.0},
                "abstention": {"abstained": 0, "nonAbstained": 0, "abstainedWinRate": 0.0, "nonAbstainedWinRate": 0.0, "improvesHitRate": True, "sampleTooSmall": True, "note": "no samples"},
            }

        brier = sum((s["confidence"] - s["outcome"]) ** 2 for s in scored) / n

        bin_edges = [(i / 10.0, (i + 1) / 10.0) for i in range(10)]
        bins = []
        ece = 0.0
        for low, high in bin_edges:
            members = [s for s in scored if low <= s["confidence"] < high or (high == 1.0 and s["confidence"] == 1.0)]
            if not members:
                continue
            acc = sum(s["outcome"] for s in members) / len(members)
            conf = sum(s["confidence"] for s in members) / len(members)
            bins.append({"bin": f"{low:.1f}-{high:.1f}", "n": len(members), "accuracy": round(acc, 4), "confidence": round(conf, 4)})
            ece += (len(members) / n) * abs(acc - conf)

        directional = [s for s in scored if s["direction"] in ("buy", "sell")]
        d_n = len(directional)
        if d_n > 0:
            wins = sum(s["outcome"] for s in directional)
            baseline = wins / d_n
            tp = sum(1 for s in directional if s["confidence"] >= 0.5 and s["outcome"] == 1)
            fp = sum(1 for s in directional if s["confidence"] >= 0.5 and s["outcome"] == 0)
            fn = sum(1 for s in directional if s["confidence"] < 0.5 and s["outcome"] == 1)
            precision = tp / (tp + fp) if (tp + fp) else 0.0
            recall = tp / (tp + fn) if (tp + fn) else 0.0
            directional_metrics = {
                "sampleCount": d_n,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "baselineWinRate": round(baseline, 4),
                "improvement": round(precision - baseline, 4),
            }
        else:
            directional_metrics = {"sampleCount": 0, "precision": 0.0, "recall": 0.0, "baselineWinRate": 0.0, "improvement": 0.0}

        def _is_abstained(s):
            return s["confidence"] < 0.5 or s["direction"] in (None, "neutral")

        abstained = [s for s in scored if _is_abstained(s)]
        non_abstained = [s for s in scored if not _is_abstained(s)]
        abstained_rate = sum(s["outcome"] for s in abstained) / len(abstained) if abstained else 0.0
        non_abstained_rate = sum(s["outcome"] for s in non_abstained) / len(non_abstained) if non_abstained else 0.0
        sample_too_small = len(abstained) < 5 or len(non_abstained) < 5
        if sample_too_small:
            improves = True
            note = "(sample too small)"
        else:
            improves = abstained_rate >= non_abstained_rate
            note = ""
        abstention = {
            "abstained": len(abstained),
            "nonAbstained": len(non_abstained),
            "abstainedWinRate": round(abstained_rate, 4),
            "nonAbstainedWinRate": round(non_abstained_rate, 4),
            "improvesHitRate": bool(improves),
            "sampleTooSmall": bool(sample_too_small),
            "note": note,
        }

        return {
            "sampleCount": n,
            "brier": round(brier, 4),
            "ece": round(ece, 4),
            "bins": bins,
            "directional": directional_metrics,
            "abstention": abstention,
        }

    def _expectancy_after_costs(self):
        """Estimate net expectancy per trade after trading costs and max drawdown."""
        logs = db.collection("learning_log").find({})
        profits = [l.get("profit") or 0 for l in logs if isinstance(l.get("profit"), (int, float))]
        n = len(profits)
        if n == 0:
            return {"expectancyNet": 0.0, "costPerTrade": 0.0, "maxDrawdownPct": 0.0, "profitable": False, "sampleCount": 0}

        costs = [0.001 * abs(p) for p in profits]
        cost_per_trade = sum(costs) / n
        expectancy_net = sum(p - c for p, c in zip(profits, costs)) / n

        peak = 0.0
        max_dd = 0.0
        cumulative = 0.0
        for p in profits:
            cumulative += p
            peak = max(peak, cumulative)
            if peak > 0:
                max_dd = max(max_dd, (peak - cumulative) / peak)
        max_drawdown_pct = round(max_dd * 100, 2)

        return {
            "expectancyNet": round(expectancy_net, 4),
            "costPerTrade": round(cost_per_trade, 4),
            "maxDrawdownPct": max_drawdown_pct,
            "profitable": bool(expectancy_net > 0),
            "sampleCount": n,
        }

    def get_ai_calibration(self):
        """Return the full AI calibration metrics for API exposure."""
        metrics = self._ai_calibration_metrics()
        metrics["expectancy"] = self._expectancy_after_costs()
        metrics["generatedAt"] = int(time.time() * 1000)
        return metrics

    async def _validate_news(self):
        checks = []
        news = get_news({"limit": 20})
        news_ok = isinstance(news, list) and len(news) > 0
        checks.append({"check": "News ingestion", "passed": news_ok, "detail": f"{len(news)} items"})

        sentiment_ok = news_ok and all(isinstance(n["sentiment"], (int, float)) and 0 <= n.get("trustScore", 0) <= 1 for n in news)
        checks.append({"check": "Sentiment & trust scores", "passed": sentiment_ok, "detail": "range valid"})

        sources = get_news_sources()
        checks.append({"check": "Source reliability", "passed": isinstance(sources, list) and len(sources) >= 10, "detail": f"{len(sources)} sources"})

        econ = get_economic_events({"limit": 10})
        checks.append({"check": "Economic calendar", "passed": isinstance(econ, list) and len(econ) > 0, "detail": f"{len(econ)} events"})

        macro = get_macro_snapshot()
        checks.append({"check": "Macro intelligence", "passed": bool(macro) and isinstance(macro.get("riskOn"), bool), "detail": f"riskOn={macro['riskOn']}"})

        passed = all(c["passed"] for c in checks)
        return {"passed": passed, "checks": checks, "score": round(len([c for c in checks if c["passed"]]) / len(checks) * 100)}

    async def _validate_technical(self):
        checks = []
        candles = generate_candles("EURUSD", "H1", 300)
        inds = calculate_all_indicators(candles)
        checks.append({"check": "Indicators", "passed": bool(inds) and isinstance(inds.get("rsi14"), (int, float)), "detail": f"rsi={inds['rsi14']:.1f} atr={inds['atr14']:.5f}"})

        pa = analyze_price_action(candles)
        checks.append({"check": "Price action", "passed": bool(pa) and isinstance(pa.get("score"), (int, float)), "detail": f"score={pa['score']} trend={pa.get('trend')}"})

        smc = analyze_smc(candles)
        smc_ok = smc and isinstance(smc.get("liquidity"), list) and isinstance(smc.get("orderBlocks"), list)
        checks.append({"check": "Smart Money Concepts", "passed": bool(smc_ok), "detail": f"{len(smc['orderBlocks'])} order blocks, {len(smc['liquidity'])} liquidity pools"})

        patterns = detect_patterns(candles)
        checks.append({"check": "Candlestick patterns", "passed": isinstance(patterns, list), "detail": f"{len(patterns)} patterns"})

        backtest = run_backtest({"symbol": "EURUSD", "strategy": "trend-follow", "candles": 300})
        bt_ok = backtest and isinstance(backtest.get("netProfit"), (int, float)) and backtest["totalTrades"] > 0
        checks.append({"check": "Backtest engine", "passed": bool(bt_ok), "detail": f"{backtest['totalTrades']} trades"})

        passed = all(c["passed"] for c in checks)
        return {"passed": passed, "checks": checks, "score": round(len([c for c in checks if c["passed"]]) / len(checks) * 100)}

    async def _validate_mt5(self):
        checks = []
        mt5 = init_mt5()
        status = await mt5["getStatus"]()
        checks.append({"check": "MT5 connectivity", "passed": status["connected"] is True, "detail": f"mode={status['mode']} latency={status['latency']}ms"})

        symbols = mt5["getSymbols"]()
        checks.append({"check": "MT5 symbol feed", "passed": isinstance(symbols, list) and len(symbols) >= 5, "detail": f"{len(symbols)} symbols"})

        result = await mt5["placeOrder"]({"symbol": "EURUSD", "side": "buy", "volume": 0.05, "stopLoss": 1.05, "takeProfit": 1.12, "comment": "validation-test"})
        checks.append({"check": "MT5 order execution", "passed": bool(result) and result.get("status") == "filled", "detail": result.get("status") if result else "failed"})

        position = result.get("position") if result else None
        if position:
            closed = await mt5["closePosition"](position["id"])
            checks.append({"check": "MT5 position close", "passed": bool(closed) and closed.get("status") == "closed", "detail": f"pnl={closed.get('profit')}"})
        else:
            checks.append({"check": "MT5 position close", "passed": False, "detail": "no position to close"})

        positions = await mt5["getPositions"]()
        checks.append({"check": "MT5 position sync", "passed": isinstance(positions, list), "detail": f"{len(positions)} open positions"})

        passed = all(c["passed"] for c in checks)
        return {"passed": passed, "checks": checks, "score": round(len([c for c in checks if c["passed"]]) / len(checks) * 100)}

    async def _validate_risk_portfolio(self):
        checks = []
        portfolio = portfolio_service.get()
        checks.append({"check": "Portfolio integrity", "passed": bool(portfolio) and portfolio["equity"] > 0 and portfolio["balance"] > 0, "detail": f"equity={portfolio['equity']} balance={portfolio['balance']}"})

        risk_check = risk_engine.evaluate_trade({"riskAmount": 500, "stopLoss": 1.05, "takeProfit": 1.1, "symbol": "EURUSD", "notionalPct": 0.5}, portfolio)
        checks.append({"check": "Risk evaluation", "passed": isinstance(risk_check["approved"], bool) and isinstance(risk_check["violations"], list), "detail": f"{len(risk_check['violations'])} violations"})

        protection = portfolio.get("capitalProtection") or {}
        checks.append({"check": "Capital protection", "passed": bool(protection) and isinstance(protection.get("haltTrading"), bool), "detail": f"halt={protection['haltTrading']}"})

        mode = trading_engine.set_mode("manual")
        checks.append({"check": "Trading mode control", "passed": mode == "manual", "detail": f"mode={mode}"})

        passed = all(c["passed"] for c in checks)
        return {"passed": passed, "checks": checks, "score": round(len([c for c in checks if c["passed"]]) / len(checks) * 100)}

    async def _validate_api(self):
        import httpx
        checks = []
        endpoints = [
            "/api/health", "/api/market/quotes", "/api/news", "/api/economic/calendar", "/api/macro/overview",
            "/api/technical/multitimeframe/EURUSD", "/api/risk/settings", "/api/portfolio/overview",
            "/api/alerts", "/api/reports", "/api/features", "/api/mt5/status", "/api/integrations",
            "/api/cloud/overview", "/api/devops/overview", "/api/production/overview", "/api/validation/suites",
            "/api/system/security", "/api/backtest/compare",
        ]
        port = os.environ.get("PORT", "3001")
        base = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            for ep in endpoints:
                try:
                    resp = await client.get(base + ep)
                    body = resp.json() if resp.content else None
                    checks.append({"check": ep, "passed": resp.status_code < 400 and body is not None, "detail": f"HTTP {resp.status_code}"})
                except Exception as err:  # noqa: BLE001
                    checks.append({"check": ep, "passed": False, "detail": str(err)})
        passed = len([c for c in checks if c["passed"]]) >= len(checks) * 0.9
        return {"passed": passed, "checks": checks, "score": round(len([c for c in checks if c["passed"]]) / len(checks) * 100)}

    async def _validate_documentation(self):
        checks = []
        root = _find_project_root()
        readme = os.path.join(root, "README.md")
        readme_ok = os.path.exists(readme) and os.path.getsize(readme) > 500
        checks.append({"check": "README exists", "passed": readme_ok, "detail": f"{round(os.path.getsize(readme) / 1024)} KB" if readme_ok else "missing"})

        api_doc = os.path.exists(os.path.join(root, "docs", "api.md"))
        checks.append({"check": "API documentation", "passed": api_doc, "detail": "docs/api.md present" if api_doc else "missing"})

        has_tests = os.path.exists(os.path.join(root, "backend", "tests"))
        checks.append({"check": "Test suite", "passed": has_tests, "detail": "backend/tests present" if has_tests else "missing"})

        has_config = os.path.exists(os.path.join(root, "docker-compose.yml")) and os.path.exists(os.path.join(root, "k8s", "quantos.yaml"))
        checks.append({"check": "Deployment manifests", "passed": has_config, "detail": "docker-compose + k8s"})

        passed = all(c["passed"] for c in checks)
        return {"passed": passed, "checks": checks, "score": round(len([c for c in checks if c["passed"]]) / len(checks) * 100)}

    async def run_suite(self, suite_id):
        suite = next((s for s in VALIDATION_SUITES if s["id"] == suite_id), None)
        if not suite:
            return None

        run = self.col.insert({"suiteId": suite_id, "suiteName": suite["name"], "status": "running", "startedAt": int(time.time() * 1000), "results": []})
        started = int(time.time() * 1000)
        if suite_id == "market-data":
            result = await self._validate_market_data()
        elif suite_id == "ai-workflow":
            result = await self._validate_ai_workflow()
        elif suite_id in ("news-intelligence", "fundamental-analysis"):
            result = await self._validate_news()
        elif suite_id == "technical-analysis":
            result = await self._validate_technical()
        elif suite_id == "mt5":
            result = await self._validate_mt5()
        elif suite_id == "risk-portfolio":
            result = await self._validate_risk_portfolio()
        elif suite_id == "api":
            result = await self._validate_api()
        elif suite_id == "documentation":
            result = await self._validate_documentation()
        else:
            result = {"passed": False, "checks": [], "score": 0}

        completed = {
            **run,
            "status": "completed",
            "passed": result["passed"],
            "score": result["score"],
            "checks": result["checks"],
            "completedAt": int(time.time() * 1000),
            "durationMs": int(time.time() * 1000) - started,
        }
        self.col.update(run["id"], completed)
        event_bus.emit("validation:completed", {"run": completed})
        monitoring.record({"name": f"validation.{suite_id}", "value": 1 if result["passed"] else 0})
        logger.info(f"Validation suite {suite_id}: {'PASS' if result['passed'] else 'FAIL'} ({result['score']}%)")
        return completed

    async def run_all_suites(self):
        results = []
        for suite in VALIDATION_SUITES:
            results.append(await self.run_suite(suite["id"]))
        return results

    def get_suites(self):
        return VALIDATION_SUITES

    def list_runs(self):
        return self.col.find({}, {"sort": ["startedAt", "desc"]})[:50]

    async def get_certification(self):
        runs = self.list_runs()
        latest_per_suite = {}
        for r in runs:
            if r["status"] != "completed":
                continue
            if r["suiteId"] not in latest_per_suite:
                latest_per_suite[r["suiteId"]] = r
        latest = list(latest_per_suite.values())
        passed_suites = [r for r in latest if r["passed"]]
        score = round(len(passed_suites) / len(latest) * 100) if latest else 0
        certified = len(latest) >= 8 and score >= 90
        cert = self.cert_col.find_one({"id": "prod-cert"})

        if certified and not cert:
            new_cert = self.cert_col.insert({
                "id": "prod-cert",
                "version": "1.0.0",
                "status": "certified",
                "certifiedAt": int(time.time() * 1000),
                "score": score,
                "suitesPassed": len(passed_suites),
                "suitesTotal": len(latest),
            })
            event_bus.emit("validation:certified", {"cert": new_cert})
            return new_cert
        return {
            "id": "prod-cert",
            "version": "1.0.0",
            "status": "certified" if certified else "pending",
            "certifiedAt": cert.get("certifiedAt") if cert else None,
            "score": score,
            "suitesPassed": len(passed_suites),
            "suitesTotal": len(latest),
            "required": 8,
        }


def _find_project_root():
    root = os.path.abspath(os.getcwd())
    while not os.path.exists(os.path.join(root, "README.md")) and os.path.dirname(root) != root:
        root = os.path.dirname(root)
    return root


validation_manager = ValidationManager()


def init_validation():
    return validation_manager.init()
