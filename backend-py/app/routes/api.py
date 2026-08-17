"""FastAPI router mirroring the Node routes/index.js API surface."""
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ..config import settings
from ..foundation.event_bus import event_bus, get_event_history
from ..foundation.monitoring import monitoring
from ..foundation.scheduler import scheduler
from ..foundation.queue import queue_system
from ..foundation.workers import workers
from ..foundation.provider_framework import providers
from ..foundation.feature_flags import feature_flags
from ..foundation.rate_limit import rate_limiter
from ..foundation.json_store import db
from ..foundation.idempotency import idempotency_store
from ..foundation.api_analytics import api_analytics

from ..modules.marketdata.engine import get_quote, get_order_book, get_trades, generate_candles, get_market_session, INSTRUMENTS
from ..modules.news.engine import get_news, get_news_sources, add_manual_source
from ..modules.economic.engine import get_economic_events, get_high_impact_events, with_ai_fields
from ..modules.macro.engine import get_macro_snapshot, get_correlation_matrix, correlate_with_quote
from ..modules.historical.engine import get_historical_snapshot, replay_market, pattern_matching, get_similar_events
from ..modules.technical.indicators import calculate_all_indicators
from ..modules.technical.candlesticks import analyze_candlesticks
from ..modules.technical.price_action import analyze_price_action
from ..modules.technical.smc import analyze_smc
from ..modules.technical.multi_timeframe import aggregate_analysis
from ..modules.ai.decision_pipeline import analyze_symbol_pipeline
from ..modules.ai.memory import ai_memory, vector_store, rag_query
from ..modules.ai.learning import learning_engine
from ..modules.ai.model_registry import model_registry
from ..modules.risk.engine import risk_engine
from ..modules.portfolio.service import portfolio_service
from ..modules.trading.engine import trading_engine
from ..modules.backtest.engine import run_backtest, compare_strategies
from ..modules.alerts.service import alert_service
from ..modules.reports.service import generate_report, get_reports, export_report
from ..modules.research.lab import run_strategy_builder, create_experiment, list_experiments, run_notebook
from ..modules.features.store import get_features, register_feature, compute_features
from ..modules.pipeline.manager import run_pipeline, list_pipelines, get_pipeline_stats
from ..modules.observability.init import init_observability
from ..modules.security.module import get_security_dashboard, list_api_keys, create_api_key, get_audit_logs
from ..modules.admin.service import get_system_dashboard, get_jobs, run_job, get_configuration, update_configuration
from ..modules.users.service import list_users, create_user, authenticate, update_preferences, list_organizations
from ..modules.integrations.service import list_integrations, configure_integration, test_integration
from ..modules.multiasset.overview import get_asset_classes, get_multi_asset_overview, get_instruments_by_class
from ..modules.mt5.adapter import init_mt5
from ..modules.cloud.infrastructure import cloud_infrastructure
from ..modules.devops.manager import devops_manager
from ..modules.production.readiness import production_readiness
from ..modules.validation.system import validation_manager
from ..modules.marketdata.instrument_specs import instrument_specs, get_instrument_spec
from ..modules.risk.capital_protection import capital_protection
from ..modules.risk.deterministic import position_sizer, sltp_calculator, risk_score_engine
from ..modules.validation.engine import validation_engine
from ..modules.execution.modes import trading_modes, TRADING_PROFILES
from ..modules.execution.auto_controller import auto_trade_controller
from ..modules.execution.profit_protection import profit_protection
from ..modules.execution.thesis import thesis_manager, opposite_news_engine
from ..modules.execution.mt5_safety import mt5_safety
from ..modules.ai.consensus import dynamic_consensus, custom_agent_registry
from ..modules.portfolio.performance import performance_analytics
from ..modules.backtest.advanced import walk_forward, monte_carlo


def _qint(value, fallback):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _pg_enabled():
    try:
        from ..persistence import is_postgres_enabled

        return is_postgres_enabled()
    except Exception:  # noqa: BLE001 - migration layer must never break core
        return False


def _qfloat(value, fallback):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _normalize_decision(d):
    """Unify AI decision records from both the DecisionCenter and the
    repository schemas into the shape the frontend expects.

    DecisionCenter records carry ``consensus``/``confidence`` objects while
    repository-persisted records carry flat ``direction``/``confidence``
    scalars. Both may coexist in the shared ``ai_decisions`` store, so every
    record is normalized before it is served to the UI.
    """
    consensus = d.get("consensus") if isinstance(d.get("consensus"), dict) else {}
    if not consensus:
        consensus = {
            "direction": d.get("direction", "neutral"),
            "buyWeight": 0.0,
            "sellWeight": 0.0,
            "neutralWeight": 1.0,
            "strength": d.get("confidence") or 0.0,
            "agreement": 0.0,
        }
    confidence = d.get("confidence")
    if not isinstance(confidence, dict):
        score = confidence if isinstance(confidence, (int, float)) else 0.0
        confidence = {
            "score": score,
            "level": "high" if score >= 0.7 else ("medium" if score >= 0.4 else "low"),
            "agreement": 0.0,
            "avgAgentConfidence": 0.0,
            "contextQuality": 0.0,
        }
    normalized = dict(d)
    normalized["consensus"] = consensus
    normalized["confidence"] = confidence
    return normalized


def _version_redirect(request, version="v1"):
    """Rewrite an incoming request path to the versioned prefix.

    Maps `<API_PREFIX>/<version>/...` to `<API_PREFIX>/...` so versioned
    requests resolve to the unversioned routes below. Applied by the
    versioning middleware in foundation/middleware.py.
    """
    prefix = settings.API_PREFIX
    marker = f"{prefix}/{version}"
    path = request.url.path
    if path == marker:
        return prefix
    if path.startswith(marker + "/"):
        return prefix + path[len(marker):]
    return path


def create_api_router():
    router = APIRouter()
    router.version = "v1"
    mt5 = init_mt5()

    @router.get("/health")
    def health():
        return {"status": "up", "timestamp": int(time.time() * 1000), "uptime": time.time() - _START}

    @router.get("/system/overview")
    async def system_overview():
        health = init_observability()["getHealth"]()
        return {
            **health,
            "cloud": cloud_infrastructure.get_overview()["summary"],
            "devops": devops_manager.get_overview()["summary"],
            "production": production_readiness.get_overall()["goLiveStatus"],
            "validation": await validation_manager.get_certification(),
            "timestamp": int(time.time() * 1000),
        }

    @router.get("/system/metrics")
    def system_metrics(request: Request):
        name = request.query_params.get("name") or "app.requests"
        opts = {}
        since = request.query_params.get("since")
        limit = request.query_params.get("limit")
        if since:
            opts["since"] = _qint(since, 0)
        if limit:
            opts["limit"] = _qint(limit, 100)
        return monitoring.query(name, opts)

    @router.get("/system/events")
    def system_events(request: Request):
        topic = request.query_params.get("topic")
        return get_event_history(topic, _qint(request.query_params.get("limit"), 200))

    @router.get("/system/providers")
    def system_providers(request: Request):
        category = request.query_params.get("category")
        return [{"id": p["id"], "name": p["name"], "category": p["category"], "enabled": p["enabled"]} for p in providers.list(category)]

    @router.get("/system/ai/providers/health")
    def ai_provider_health():
        from ..modules.ai.provider_extensions import provider_health_status

        return {"status": "ok", "providers": provider_health_status()}

    @router.get("/system/ai/models/status")
    def ai_models_status():
        from ..modules.ai.extra_providers import ai_models_status as _models_status

        return _models_status()

    @router.get("/system/ai/usage")
    def ai_usage():
        from ..modules.ai.provider_extensions import cost_tracker

        return cost_tracker.status()

    @router.get("/system/scheduler")
    def _scheduler():
        return scheduler.status()

    @router.get("/system/queues")
    def _queues():
        return queue_system.snapshot()

    @router.get("/system/workers")
    def _workers():
        return workers.status()

    @router.get("/system/features")
    def _features():
        return feature_flags.all()

    @router.post("/system/features/{key}")
    def set_feature(key: str, body: dict):
        return feature_flags.set(key, body.get("value"), body.get("description"))

    @router.get("/market/quotes")
    def market_quotes():
        return [get_quote(i["symbol"]) for i in INSTRUMENTS]

    @router.get("/market/quotes/{symbol}")
    def market_quote(symbol: str):
        return get_quote(symbol.upper())

    @router.get("/market/orderbook/{symbol}")
    def market_orderbook(symbol: str, request: Request):
        return get_order_book(symbol.upper(), _qint(request.query_params.get("depth"), 10))

    @router.get("/market/trades/{symbol}")
    def market_trades(symbol: str, request: Request):
        return get_trades(symbol.upper(), _qint(request.query_params.get("count"), 50))

    @router.get("/market/candles/{symbol}")
    def market_candles(symbol: str, request: Request):
        tf = request.query_params.get("timeframe") or "H1"
        count = _qint(request.query_params.get("count"), 200)
        return generate_candles(symbol.upper(), tf, count)

    @router.get("/market/sessions")
    def market_sessions():
        return get_market_session()

    @router.get("/market/instruments")
    def market_instruments():
        return INSTRUMENTS

    @router.get("/news")
    def news(request: Request):
        return get_news(dict(request.query_params))

    @router.get("/news/sources")
    def news_sources():
        return get_news_sources()

    @router.get("/news/sources/summary")
    def news_sources_summary():
        from ..modules.news.engine import get_news_sources_summary
        return get_news_sources_summary()

    @router.post("/news/sources")
    def add_source(body: dict):
        return add_manual_source(body)

    @router.post("/news/ingest")
    def news_ingest(body: dict):
        event_bus.emit("news:ingest", {"payload": body})
        return {"status": "queued"}

    @router.get("/news/live")
    def news_live(request: Request):
        from ..modules.news.decay import get_live_news

        return get_live_news(dict(request.query_params))

    @router.post("/news/{item_id}/translate")
    def news_translate(item_id: str, lang: str = "ur"):
        from ..modules.news.engine import translate_text, get_news

        items = get_news({"limit": "200"})
        item = next((n for n in items if str(n.get("id")) == str(item_id)), None)
        if not item:
            return {"status": "error", "reason": "news-item-not-found", "lang": lang}
        translated_title = translate_text(item.get("title"), target_lang=lang)
        translated_summary = translate_text(item.get("summary"), target_lang=lang)
        return {
            "status": "ok",
            "id": item.get("id"),
            "lang": lang,
            "originalTitle": item.get("title"),
            "originalSummary": item.get("summary"),
            "translatedTitle": translated_title or item.get("title"),
            "translatedSummary": translated_summary or item.get("summary"),
            "translated": str(lang).lower() != "en" and translated_title is not None,
        }

    @router.get("/news/decay/status")
    def news_decay_status():
        from ..modules.news.decay import news_decay_engine

        return {
            "halfLifeSeconds": news_decay_engine.half_life_seconds,
            "minRelevance": news_decay_engine.min_relevance,
            "hardStaleSeconds": news_decay_engine.hard_stale_seconds,
        }

    @router.get("/news/collectors")
    def news_collectors():
        from ..modules.news.collectors import collectors_registry, WHATSAPP_DEFAULT_MODE

        return [{
            "id": c.id,
            "name": c.name,
            "collectorType": c.collector_type,
            "enabled": c.enabled,
            "mode": getattr(c, "mode", None),
            "officialReady": getattr(c, "official_ready", None),
        } for c in collectors_registry.values()]

    @router.post("/news/collectors/run")
    async def news_collectors_run(body: dict):
        import asyncio

        from ..modules.news.realtime.registry import poll_all_collectors

        limit = int(body.get("limit") or 10)

        def _run_poll():
            return asyncio.run(poll_all_collectors(limit))

        return await asyncio.to_thread(_run_poll)

    @router.post("/news/whatsapp/ingest")
    def news_whatsapp_ingest(body: dict):
        from ..modules.news.collectors import whatsapp_adapter

        adapter = whatsapp_adapter()
        if adapter is None:
            return {"status": "error", "reason": "whatsapp-adapter-not-initialized"}
        return adapter.ingest_payload(body.get("payload") or body)

    @router.get("/news/whatsapp/status")
    def news_whatsapp_status():
        from ..modules.news.collectors import whatsapp_adapter

        adapter = whatsapp_adapter()
        if adapter is None:
            return {"status": "error", "reason": "whatsapp-adapter-not-initialized"}
        return {"mode": adapter.mode, "officialReady": adapter.official_ready, "enabled": adapter.enabled}

    @router.get("/economic/calendar")
    def economic_calendar(request: Request):
        return [with_ai_fields(e) for e in get_economic_events(dict(request.query_params))]

    @router.get("/economic/high-impact")
    def economic_high_impact():
        return [with_ai_fields(e) for e in get_high_impact_events()]

    @router.get("/economic/revisions/{event_id}")
    def economic_revisions(event_id: str):
        from ..modules.economic.revisions import revision_store

        return revision_store.get_revisions(event_id)

    @router.post("/economic/revisions/{event_id}")
    def economic_apply_revision(event_id: str, body: dict):
        from ..modules.economic.revisions import apply_revision

        return apply_revision(event_id, body.get("newValue"), note=body.get("note", ""))

    @router.get("/economic/pit/{event_id}")
    def economic_pit(event_id: str, request: Request):
        from ..modules.economic.revisions import revision_store

        as_of = int(request.query_params.get("asOf") or 0)
        return {
            "eventId": event_id,
            "pit": revision_store.pit_value(event_id, as_of),
            "pitSafe": revision_store.is_pit_safe(event_id, as_of),
        }

    @router.get("/economic/reactions/{event_id}")
    def economic_reactions(event_id: str, request: Request):
        from ..modules.economic.revisions import revision_store

        return revision_store.reaction_stats(event_id, int(request.query_params.get("windowHours") or 72))

    @router.get("/macro/overview")
    def macro_overview():
        return get_macro_snapshot()

    @router.get("/macro/correlations")
    def macro_correlations(request: Request):
        symbols = request.query_params.get("symbols")
        return get_correlation_matrix(symbols)

    @router.get("/macro/correlate/{symbol}")
    def macro_correlate(symbol: str):
        return correlate_with_quote(symbol.upper())

    @router.get("/historical/overview")
    def historical_overview():
        return get_historical_snapshot()

    @router.get("/historical/replay")
    def historical_replay(request: Request):
        return replay_market(request.query_params.get("symbol"), request.query_params.get("timeframe"), _qint(request.query_params.get("count"), 200))

    @router.get("/historical/patterns")
    def historical_patterns(request: Request):
        return pattern_matching(request.query_params.get("symbol"))

    @router.get("/historical/similar")
    def historical_similar(request: Request):
        return get_similar_events(request.query_params.get("item") or {})

    @router.get("/historical/memory")
    def historical_memory(request: Request):
        from ..modules.historical.memory import market_memory

        pit = request.query_params.get("pitAsOf")
        return market_memory.query(
            symbol=request.query_params.get("symbol"),
            driver=request.query_params.get("driver"),
            category=request.query_params.get("category"),
            k=int(request.query_params.get("limit") or 5),
            pit_as_of=int(pit) if pit else None,
        )

    @router.get("/historical/named-events")
    def historical_named_events(request: Request):
        from ..modules.historical.memory import named_events

        return named_events(request.query_params.get("symbol"), request.query_params.get("category"))

    @router.get("/technical/indicators/{symbol}")
    def technical_indicators(symbol: str, request: Request):
        tf = request.query_params.get("timeframe") or "H1"
        candles = generate_candles(symbol.upper(), tf, 300)
        return calculate_all_indicators(candles)

    @router.get("/technical/volume/{symbol}")
    def technical_volume(symbol: str, request: Request):
        from ..modules.technical.volume_analysis import volume_analysis

        tf = request.query_params.get("timeframe") or "H1"
        candles = generate_candles(symbol.upper(), tf, int(request.query_params.get("count") or 300))
        return {"symbol": symbol, "timeframe": tf, "volume": volume_analysis(candles)}

    @router.get("/technical/candlesticks/{symbol}")
    def technical_candlesticks(symbol: str, request: Request):
        tf = request.query_params.get("timeframe") or "H1"
        candles = generate_candles(symbol.upper(), tf, 200)
        return analyze_candlesticks(candles)

    @router.get("/technical/price-action/{symbol}")
    def technical_price_action(symbol: str, request: Request):
        tf = request.query_params.get("timeframe") or "H1"
        candles = generate_candles(symbol.upper(), tf, 300)
        return analyze_price_action(candles)

    @router.get("/technical/smc/{symbol}")
    def technical_smc(symbol: str, request: Request):
        tf = request.query_params.get("timeframe") or "H1"
        candles = generate_candles(symbol.upper(), tf, 300)
        return analyze_smc(candles, tf)

    @router.get("/technical/multitimeframe/{symbol}")
    def technical_multitimeframe(symbol: str):
        candles_by_tf = {}
        for tf in ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"]:
            candles_by_tf[tf] = generate_candles(symbol.upper(), tf, 100 if tf == "W1" else 250)
        return aggregate_analysis(candles_by_tf)

    @router.get("/technical/confluence/{symbol}")
    def technical_confluence(symbol: str):
        from ..modules.technical.confluence import compute_confluence

        candles_by_tf = {}
        for tf in ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"]:
            candles_by_tf[tf] = generate_candles(symbol.upper(), tf, 100 if tf == "W1" else 250)
        return compute_confluence(candles_by_tf, symbol=symbol.upper())

    @router.get("/ai/analyze/{symbol}")
    @router.post("/ai/analyze/{symbol}")
    async def ai_analyze(symbol: str):
        return await _ai_analyze(symbol)

    async def _ai_analyze(symbol):
        # Real 5-agent decision pipeline (News/Historical/Macro/Technical/Risk
        # + enabled custom agents). Replaces the old rule-based consensus center.
        return await analyze_symbol_pipeline(symbol.upper())

    @router.get("/ai/debate/{symbol}/latest")
    def ai_debate_latest(symbol: str):
        col = db.collection("debate_history")
        rows = col.find({"symbol": symbol.upper()}, {"sort": ["timestamp", "desc"]})
        if rows:
            return rows[0]
        return {"symbol": symbol.upper(), "status": "none", "available": False,
                "rating": None, "direction": "neutral", "strength": 0.0,
                "net": 0.0, "reason": "No debate has been run for this symbol yet."}

    @router.get("/ai/debate/{symbol}/history")
    def ai_debate_history(symbol: str, request: Request):
        limit = _qint(request.query_params.get("limit"), 20)
        col = db.collection("debate_history")
        rows = col.find({"symbol": symbol.upper()}, {"sort": ["timestamp", "desc"]})
        return rows[:limit]

    @router.get("/risk/debate/{symbol}/latest")
    def risk_debate_latest(symbol: str):
        from ..modules.risk.debate.portfolio_gate import get_latest_risk_debate

        row = get_latest_risk_debate(symbol.upper())
        if row:
            return row
        return {"symbol": symbol.upper(), "approved": None, "verdict": None}

    @router.get("/risk/debate/history")
    def risk_debate_history(request: Request):
        limit = _qint(request.query_params.get("limit"), 20)
        col = db.collection("risk_debate_history")
        rows = col.find({}, {"sort": ["timestamp", "desc"]})
        return rows[:limit]

    @router.get("/ai/decisions")
    def ai_decisions(request: Request):
        limit = _qint(request.query_params.get("limit"), 50)
        if _pg_enabled():
            import asyncio

            from ..persistence import decision_repository

            coro = decision_repository.list(limit=limit)
            try:
                rows = asyncio.run(coro)
            except RuntimeError:
                rows = asyncio.get_event_loop().run_until_complete(coro)
        else:
            col = db.collection("ai_decisions")
            rows = col.find({}, {"sort": ["timestamp", "desc"]})[:limit]
        return [_normalize_decision(d) for d in rows]

    @router.get("/ai/memory")
    def ai_mem(request: Request):
        return ai_memory.recent(_qint(request.query_params.get("limit"), 20))

    @router.post("/ai/memory")
    def ai_mem_post(body: dict):
        ai_memory.remember(body.get("key"), body.get("value"), body.get("ttlMs"))
        return {"status": "remembered"}

    @router.get("/ai/rag")
    def ai_rag(request: Request):
        return rag_query(request.query_params.get("q"), _qint(request.query_params.get("k"), 3))

    @router.get("/ai/vectors")
    def ai_vectors():
        return [{"id": v["id"], "text": v.get("text"), "metadata": v.get("metadata")} for v in vector_store.all()]

    @router.get("/ai/learning")
    def ai_learning():
        return learning_engine.get_state()

    @router.post("/ai/learning/record")
    def ai_learning_record(body: dict):
        return learning_engine.record_outcome(body.get("decision"), body.get("tradeResult"))

    @router.get("/ai/models")
    def ai_models():
        return model_registry.get_state()

    @router.post("/ai/models/register")
    def ai_models_register(body: dict):
        return model_registry.register(body.get("name") or "candidate", body.get("metadata") or {}, body.get("weights") or {})

    @router.post("/ai/models/{model_id}/approve")
    def ai_models_approve(model_id: str, body: dict = None):
        return model_registry.approve(model_id, (body or {}).get("reviewer") or "system")

    @router.post("/ai/models/{model_id}/reject")
    def ai_models_reject(model_id: str, body: dict = None):
        return model_registry.reject(model_id, (body or {}).get("reason") or "", (body or {}).get("reviewer") or "system")

    @router.post("/ai/models/{model_id}/promote")
    def ai_models_promote(model_id: str):
        return model_registry.promote(model_id)

    @router.post("/ai/models/rollback")
    def ai_models_rollback(body: dict = None):
        return model_registry.rollback((body or {}).get("modelId"))

    @router.get("/ai/models/drift")
    def ai_models_drift():
        return model_registry.drift_report()

    @router.get("/mt5/status")
    async def mt5_status():
        return await mt5["getStatus"]()

    @router.post("/mt5/connect")
    async def mt5_connect():
        return await mt5["connect"]()

    @router.post("/mt5/disconnect")
    async def mt5_disconnect():
        return await mt5["disconnect"]()

    @router.get("/mt5/orders")
    async def mt5_orders():
        return await mt5["getOrders"]()

    @router.get("/mt5/positions")
    async def mt5_positions():
        return await mt5["getPositions"]()

    @router.get("/mt5/history")
    async def mt5_history():
        return await mt5["getHistory"]()

    @router.get("/mt5/symbols")
    def mt5_symbols():
        return mt5["getSymbols"]()

    @router.post("/mt5/orders")
    async def mt5_orders_post(body: dict):
        return await mt5["placeOrder"](body)

    @router.get("/trading/positions")
    def trading_positions():
        return db.collection("positions").find({"status": "open"})

    @router.get("/trading/orders")
    def trading_orders(request: Request):
        return trading_engine.get_orders(dict(request.query_params))

    @router.post("/trading/orders")
    def trading_orders_post(body: dict):
        return trading_engine.place_order(body)

    @router.post("/trading/positions/{position_id}/close")
    def trading_close(position_id: str, body: dict):
        return trading_engine.close_position(position_id, body.get("reason") or "manual", body.get("price"))

    @router.post("/trading/positions/{position_id}/modify")
    def trading_modify(position_id: str, body: dict):
        return trading_engine.modify_position(position_id, body)

    @router.post("/trading/positions/{position_id}/partial")
    def trading_partial(position_id: str, body: dict):
        return trading_engine.partial_close(position_id, _qfloat(body.get("percent"), 0.5), body.get("price"))

    @router.post("/trading/positions/{position_id}/reverse")
    def trading_reverse(position_id: str):
        return trading_engine.reverse_position(position_id)

    @router.post("/trading/mode")
    def trading_mode(body: dict):
        return trading_engine.set_mode(body.get("mode"))

    @router.get("/trading/mode")
    def trading_mode_get():
        return {"mode": trading_engine.mode}

    # ---- Trading modes (Batch 17) ----
    @router.get("/execution/modes")
    def execution_modes():
        return trading_modes.get_status()

    @router.post("/execution/modes")
    def execution_modes_set(body: dict):
        return trading_modes.set_mode(body.get("mode"), body.get("actor", "user"), body.get("reason"))

    @router.post("/execution/modes/promote")
    def execution_modes_promote(body: dict):
        return trading_modes.promote(body.get("actor", "admin"))

    @router.get("/execution/profiles")
    def execution_profiles():
        return trading_modes.list_profiles()

    @router.post("/execution/profiles")
    def execution_profiles_set(body: dict):
        return trading_modes.set_profile(body.get("profile_id"))

    @router.get("/execution/schedules")
    def execution_schedules():
        return {"schedules": trading_modes.schedules}

    @router.post("/execution/schedules")
    def execution_schedules_post(body: dict):
        return trading_modes.add_schedule(body)

    @router.post("/execution/kill-switches/clear")
    def execution_kill_switches_clear(body: dict = None):
        """Clear ALL active kill switches + capital-protection gates at once.

        Safe admin-only reset: kill switches are deactivated, EMERGENCY_STOP is
        released, fail-closed triggers are cleared and the daily lock is reset.
        Trading mode returns to DISABLED (safe default).
        """
        body = body or {}
        modes_res = trading_modes.clear_kill_switches(body.get("actor", "admin"))
        capital_protection.deactivate_emergency_stop(body.get("actor", "admin"))
        for trigger in list(capital_protection.get_status().get("fail_closed") or []):
            capital_protection.clear_fail_closed(trigger)
        capital_protection.clear_daily_lock(body.get("actor", "admin"))
        return {
            "status": "ok",
            "cleared": modes_res.get("cleared", []),
            "mode": modes_res.get("mode"),
            "capital": capital_protection.get_status(),
        }

    @router.post("/execution/kill-switches/{switch}")
    def execution_kill_switch(switch: str, body: dict):
        return trading_modes.trigger_kill_switch(switch, bool(body.get("active", True)), body.get("detail"))

    @router.get("/execution/kill-switches")
    def execution_kill_switches():
        return {"kill_switches": trading_modes.kill_switches_status(), "blocked": trading_modes.blocked_reasons()}

    # ---- Auto trade controller (core confidence gating) ----
    @router.post("/execution/evaluate")
    def execution_evaluate(body: dict):
        return auto_trade_controller.evaluate(body.get("decision") or {}, body.get("context") or {})

    @router.get("/execution/suggested")
    def execution_suggested(request: Request):
        return auto_trade_controller.suggested_trades(request.query_params.get("status"))

    @router.post("/execution/suggested")
    def execution_suggested_post(body: dict):
        return auto_trade_controller.create_suggested_trade(body.get("decision") or {})

    @router.post("/execution/suggested/{trade_id}/approve")
    def execution_suggested_approve(trade_id: str, body: dict):
        return auto_trade_controller.approve_suggested(trade_id, body.get("modify"))

    @router.post("/execution/suggested/{trade_id}/reject")
    def execution_suggested_reject(trade_id: str):
        return auto_trade_controller.reject_suggested(trade_id)

    @router.get("/execution/status")
    def execution_status():
        return auto_trade_controller.status()

    # ---- Capital protection (Batch 16) ----
    @router.get("/capital/status")
    def capital_status():
        return capital_protection.get_status()

    @router.post("/capital/evaluate")
    def capital_evaluate(body: dict):
        return capital_protection.evaluate(body.get("portfolio") or {})

    @router.post("/capital/emergency-stop")
    def capital_emergency(body: dict):
        return capital_protection.activate_emergency_stop(body.get("reason") or "manual")

    @router.post("/capital/emergency-stop/clear")
    def capital_emergency_clear(body: dict):
        return capital_protection.deactivate_emergency_stop(body.get("actor", "admin"))

    @router.post("/capital/fail-closed/{trigger}")
    def capital_fail_closed(trigger: str, body: dict):
        return capital_protection.raise_fail_closed(trigger, body.get("detail") or "")

    @router.post("/capital/fail-closed/{trigger}/clear")
    def capital_fail_closed_clear(trigger: str):
        return capital_protection.clear_fail_closed(trigger)

    # ---- Validation engine (Batch 10) ----
    @router.post("/validation/evaluate")
    def validation_evaluate(body: dict):
        return validation_engine.evaluate(body.get("context") or {})

    @router.post("/validation/hard-blocker/{blocker}")
    def validation_hard_blocker(blocker: str, body: dict):
        validation_engine.raise_hard_blocker(blocker, body.get("detail") or "")
        return validation_engine.check_hard_blockers()

    @router.post("/validation/hard-blocker/{blocker}/clear")
    def validation_hard_blocker_clear(blocker: str):
        validation_engine.clear_hard_blocker(blocker)
        return validation_engine.check_hard_blockers()

    # ---- Instrument specs (Batch 04) ----
    @router.get("/instruments/specs")
    def instruments_specs():
        return instrument_specs.all()

    @router.get("/instruments/specs/{symbol}")
    def instruments_spec(symbol: str):
        spec = get_instrument_spec(symbol)
        if not spec:
            return JSONResponse({"error": "Instrument not found"}, status_code=404)
        return spec

    @router.get("/instruments/specs/{symbol}/status")
    def instruments_status(symbol: str):
        return instrument_specs.market_status(symbol)

    # ---- Deterministic risk (Batch 14) ----
    @router.post("/risk/position-size")
    def risk_position_size(body: dict):
        method = body.get("method") or "fixed_percent"
        return {"volume": position_sizer.size(method, body)}

    @router.post("/risk/sltp")
    def risk_sltp(body: dict):
        side = body.get("side")
        entry = body.get("entry")
        levels = body.get("levels") or {}
        sl = sltp_calculator.stop_loss(side, entry, levels)
        tp = sltp_calculator.take_profit(side, entry, sl["stop"], levels)
        return {"stop_loss": sl, "take_profit": tp}

    @router.post("/risk/score")
    def risk_score(body: dict):
        return risk_score_engine.score(body.get("context") or {})

    @router.post("/risk/analyze")
    def risk_analyze(body: dict):
        from ..modules.risk.analyzers import analyze_all

        return analyze_all(
            body.get("trade") or {},
            body.get("portfolio") or {},
            positions=body.get("positions"),
            atr_value=body.get("atrValue"),
            high_impact_events=body.get("highImpactEvents"),
            utc_hour=body.get("utcHour"),
        )

    @router.get("/risk/session/{symbol}")
    def risk_session(symbol: str, request: Request):
        from ..modules.risk.analyzers import session_risk_analyzer

        hour = request.query_params.get("utcHour")
        return session_risk_analyzer.analyze(int(hour) if hour else None, symbol)

    # ---- Profit protection (Batch 15) ----
    @router.post("/profit/break-even")
    def profit_break_even(body: dict):
        return profit_protection.break_even(body.get("position") or {}, body.get("quote_price"), body.get("pips_gain", 0))

    @router.post("/profit/trailing-stop")
    def profit_trailing(body: dict):
        return profit_protection.trailing_stop(body.get("position") or {}, body.get("quote_price"), body.get("atr"))

    @router.post("/profit/partial-close")
    def profit_partial(body: dict):
        return profit_protection.partial_close(body.get("position") or {}, body.get("target_pips"), body.get("entry"), body.get("quote_price"))

    @router.post("/profit/lock")
    def profit_lock(body: dict):
        return profit_protection.ai_profit_lock(body.get("position") or {}, body.get("news") or {}, body.get("market") or {})

    @router.get("/profit/actions")
    def profit_actions(request: Request):
        return profit_protection.recent_actions(_qint(request.query_params.get("limit"), 50))

    # ---- Thesis + opposite news (Batch 13) ----
    @router.post("/trading/theses")
    def thesis_create(body: dict):
        return thesis_manager.create_thesis(body.get("position_id"), body.get("thesis") or {})

    @router.get("/trading/theses/{position_id}")
    def thesis_get(position_id: str):
        return thesis_manager.get_thesis(position_id)

    @router.post("/trading/theses/{position_id}/version")
    def thesis_version(position_id: str, body: dict):
        return thesis_manager.new_version(position_id, body.get("patch") or {}, body.get("reason") or "re-analysis")

    @router.get("/trading/theses/{position_id}/history")
    def thesis_history(position_id: str):
        return thesis_manager.get_history(position_id)

    @router.post("/news/opposite-action")
    def news_opposite_action(body: dict):
        return opposite_news_engine.evaluate(body.get("position") or {}, body.get("news") or {}, body.get("thesis") or {}, body.get("context") or {})

    @router.post("/news/opposite-action/reverse")
    def news_opposite_reverse(body: dict):
        return opposite_news_engine.allow_reverse(body.get("position_id"), body.get("thesis"), bool(body.get("validation_passed")), bool(body.get("risk_approved")))

    @router.get("/news/opposite-actions")
    def news_opposite_actions(request: Request):
        return opposite_news_engine.recent(_qint(request.query_params.get("limit"), 50))

    # ---- MT5 safety envelope (Batch 12) ----
    @router.post("/mt5/safety/order")
    def mt5_safety_order(body: dict):
        order = body.get("order") or {}
        meta = body.get("meta") or {}
        envelope = mt5_safety.build_order(order, meta)
        dup = mt5_safety.duplicate_check(envelope)
        if dup["duplicate"]:
            return {"status": "duplicate-blocked", "existing": dup["existing"]}
        if mt5_safety.is_frozen(envelope.get("symbol")):
            return {"status": "execution-frozen", "symbol": envelope.get("symbol")}
        mt5_safety.record(envelope, "submitted")
        return {"status": "accepted", "envelope": envelope}

    @router.post("/mt5/safety/verify-retry")
    def mt5_safety_verify(body: dict):
        ok, evidence = mt5_safety.verify_before_retry(body.get("envelope") or body)
        return {"can_retry": ok, "evidence": evidence}

    @router.post("/mt5/safety/freeze/{symbol}")
    def mt5_safety_freeze(symbol: str, body: dict):
        return mt5_safety.freeze_symbol(symbol, body.get("reason") or "manual")

    @router.post("/mt5/safety/unfreeze/{symbol}")
    def mt5_safety_unfreeze(symbol: str):
        return mt5_safety.unfreeze_symbol(symbol)

    @router.get("/mt5/safety/frozen")
    def mt5_safety_frozen():
        return mt5_safety.frozen_symbols()

    @router.post("/mt5/safety/reconcile")
    def mt5_safety_reconcile(body: dict):
        return mt5_safety.reconcile(body.get("local") or [], body.get("mt5") or [])

    @router.get("/mt5/safety/reconciliation")
    def mt5_safety_reconciliation(request: Request):
        return mt5_safety.reconciliation_log(_qint(request.query_params.get("limit"), 50))

    # ---- Dynamic consensus (Batch 07/22) ----
    @router.post("/ai/consensus")
    def ai_consensus(body: dict):
        return dynamic_consensus.compute(body.get("votes") or [], body.get("context") or {})

    @router.get("/ai/consensus/history")
    def ai_consensus_history(request: Request):
        return dynamic_consensus.history(_qint(request.query_params.get("limit"), 50))

    @router.get("/ai/consensus/performance")
    def ai_consensus_performance():
        return dynamic_consensus.agent_performance()

    @router.get("/ai/agents")
    def ai_custom_agents():
        return custom_agent_registry.list()

    @router.post("/ai/agents")
    def ai_custom_agents_post(body: dict):
        return custom_agent_registry.create(body)

    @router.put("/ai/agents/{agent_id}")
    def ai_custom_agents_update(agent_id: str, body: dict):
        return custom_agent_registry.update(agent_id, body)

    @router.delete("/ai/agents/{agent_id}")
    def ai_custom_agents_delete(agent_id: str):
        return custom_agent_registry.remove(agent_id)

    # ---- Performance analytics (Batch 19) ----
    @router.get("/performance")
    def performance(request: Request):
        return performance_analytics.compute(request.query_params.get("source"))

    @router.get("/performance/time")
    def performance_time(request: Request):
        return performance_analytics.time_analytics(request.query_params.get("source"))

    @router.get("/performance/categories")
    def performance_categories():
        return performance_analytics.category_analytics()

    @router.get("/performance/ai")
    def performance_ai():
        return performance_analytics.ai_performance()

    # ---- Backtest advanced (Batch 20) ----
    @router.post("/backtest/walk-forward")
    def backtest_walk_forward(body: dict):
        return walk_forward(body)

    @router.post("/backtest/monte-carlo")
    def backtest_monte_carlo(body: dict):
        base = run_backtest(body.get("params") or {})
        return monte_carlo(base, _qint(body.get("simulations"), 1000))

    @router.get("/risk/settings")
    def risk_settings():
        return risk_engine.get_settings()

    @router.post("/risk/settings/{setting_id}")
    def risk_setting(setting_id: str, body: dict):
        return risk_engine.update_setting(setting_id, body.get("value"))

    @router.get("/portfolio/overview")
    def portfolio_overview():
        return portfolio_service.get()

    @router.get("/portfolio/equity-curve")
    def portfolio_equity_curve():
        return portfolio_service.equity_curve()

    @router.get("/portfolio/daily")
    def portfolio_daily(request: Request):
        return portfolio_service.daily_summary(_qint(request.query_params.get("days"), 30))

    @router.post("/backtest/run")
    def backtest_run(body: dict):
        return run_backtest(body)

    @router.post("/backtest/compare")
    def backtest_compare_post(body: dict):
        return compare_strategies(body)

    @router.get("/backtest/compare")
    def backtest_compare_get(request: Request):
        return compare_strategies(dict(request.query_params))

    @router.get("/alerts")
    def alerts(request: Request):
        return alert_service.get_alerts(dict(request.query_params))

    @router.post("/alerts/{alert_id}/read")
    def alert_read(alert_id: str):
        return alert_service.mark_read(alert_id)

    @router.get("/alerts/rules")
    def alert_rules():
        return alert_service.get_rules()

    @router.post("/alerts/rules")
    def alert_add_rule(body: dict):
        return alert_service.add_rule(body)

    @router.post("/alerts/notify")
    def alert_notify(body: dict):
        return alert_service.notify(body.get("subject"), body.get("message"), body.get("severity"), body.get("channels"))

    @router.get("/alerts/stats")
    def alert_stats():
        return alert_service.stats()

    @router.get("/reports/generate")
    def reports_generate_get(request: Request):
        return generate_report(request.query_params.get("type"))

    @router.post("/reports/generate")
    def reports_generate_post(body: dict):
        return generate_report(body.get("type"))

    @router.get("/reports")
    def reports(request: Request):
        return get_reports(dict(request.query_params))

    @router.get("/reports/{report_id}/export")
    def report_export(report_id: str, request: Request):
        fmt = request.query_params.get("format") or "json"
        data = export_report(report_id, fmt)
        if data is None:
            return JSONResponse({"error": "Report not found"}, status_code=404)
        media = "text/csv" if fmt == "csv" else "application/json"
        return Response(content=data, media_type=media)

    @router.get("/reports/{report_id}/render")
    def report_render(report_id: str, request: Request):
        from ..modules.reports.renderers import render_report

        fmt = request.query_params.get("format") or "markdown"
        data = render_report(report_id, fmt)
        if data is None:
            return JSONResponse({"error": "Report not found"}, status_code=404)
        media = {
            "markdown": "text/markdown", "md": "text/markdown",
            "html": "text/html",
            "excel": "text/csv", "xlsx": "text/csv", "csv": "text/csv",
        }.get(fmt, "text/plain")
        return Response(content=data, media_type=media)

    @router.post("/research/strategy-builder")
    def research_strategy_builder(body: dict):
        return run_strategy_builder(body)

    @router.post("/research/experiments")
    def research_experiments(body: dict):
        return create_experiment(body)

    @router.get("/research/experiments")
    def research_experiments_list():
        return list_experiments()

    @router.post("/research/notebooks/run")
    def research_notebook(body: dict):
        return run_notebook(body)

    @router.get("/features")
    def features(request: Request):
        return get_features(dict(request.query_params))

    @router.post("/features")
    def features_post(body: dict):
        return register_feature(body)

    @router.get("/features/compute/{symbol}")
    def features_compute(symbol: str):
        return compute_features(symbol.upper())

    @router.get("/pipelines")
    def pipelines():
        return list_pipelines()

    @router.post("/pipelines/{pipeline_id}/run")
    def pipeline_run(pipeline_id: str):
        return run_pipeline(pipeline_id)

    @router.get("/pipelines/stats")
    def pipeline_stats():
        return get_pipeline_stats()

    @router.get("/monitoring/health")
    def monitoring_health():
        return init_observability()["getHealth"]()

    @router.get("/admin/dashboard")
    def admin_dashboard():
        return get_system_dashboard()

    @router.get("/admin/jobs")
    def admin_jobs():
        return get_jobs()

    @router.post("/admin/jobs/{job_id}/run")
    def admin_job_run(job_id: str):
        return run_job(job_id)

    @router.get("/admin/config")
    def admin_config():
        return get_configuration()

    @router.post("/admin/config")
    def admin_config_post(body: dict):
        return update_configuration(body.get("key"), body.get("value"))

    @router.get("/admin/audit")
    def admin_audit(request: Request):
        return get_audit_logs(dict(request.query_params))

    @router.get("/security/dashboard")
    def security_dashboard():
        return get_security_dashboard()

    @router.get("/security/keys")
    def security_keys():
        return list_api_keys()

    @router.post("/security/keys")
    def security_keys_post(body: dict):
        return create_api_key(body.get("name"), body.get("role"))

    @router.post("/security/mfa/setup")
    def security_mfa_setup(body: dict):
        from ..modules.security.hardening import totp_provider

        return {"secret": totp_provider.secret, "uri": totp_provider.provisioning_uri(body.get("account") or "quantos-user")}

    @router.post("/security/mfa/verify")
    def security_mfa_verify(body: dict):
        from ..modules.security.hardening import totp_provider

        ok = totp_provider.verify(body.get("code"))
        return {"valid": ok}

    @router.post("/security/vault/set")
    def security_vault_set(body: dict):
        from ..modules.security.hardening import secret_vault

        return secret_vault.set(body.get("name"), body.get("value"))

    @router.get("/security/vault/names")
    def security_vault_names():
        from ..modules.security.hardening import secret_vault

        return {"secrets": secret_vault.list_names()}

    @router.post("/security/csrf/issue")
    def security_csrf_issue(body: dict):
        from ..modules.security.hardening import csrf_guard

        return {"token": csrf_guard.issue(body.get("userId") or "user")}

    @router.post("/security/csrf/verify")
    def security_csrf_verify(body: dict):
        from ..modules.security.hardening import csrf_guard

        return {"valid": csrf_guard.verify(body.get("token"), body.get("userId"))}

    @router.post("/security/ssrf/check")
    def security_ssrf_check(body: dict):
        from ..modules.security.hardening import ssrf_guard

        return ssrf_guard.validate(body.get("url") or "")

    @router.post("/security/webhook/verify")
    def security_webhook_verify(body: dict):
        from ..modules.security.hardening import webhook_signer

        payload = body.get("payload")
        payload_bytes = payload if isinstance(payload, bytes) else str(payload).encode()
        return {"valid": webhook_signer.verify(payload_bytes, body.get("signature") or "")}

    @router.get("/users")
    def users():
        return list_users()

    @router.post("/users")
    def users_post(body: dict):
        try:
            return create_user(body)
        except ValueError as err:
            return JSONResponse({"error": str(err)}, status_code=400)

    @router.post("/auth/login")
    def auth_login(body: dict):
        result = authenticate(body.get("username"), body.get("password"))
        if not result:
            return JSONResponse({"error": "Invalid credentials"}, status_code=401)
        return result

    @router.get("/users/organizations")
    def users_organizations():
        return list_organizations()

    @router.get("/integrations")
    def integrations():
        return list_integrations()

    @router.post("/integrations/{integration_id}/configure")
    def integration_configure(integration_id: str, body: dict):
        return configure_integration(integration_id, body)

    @router.post("/integrations/{integration_id}/test")
    def integration_test(integration_id: str):
        return test_integration(integration_id)

    @router.get("/assets/classes")
    def assets_classes():
        return get_asset_classes()

    @router.get("/assets/overview")
    def assets_overview():
        return get_multi_asset_overview()

    @router.get("/assets/{asset_class}/instruments")
    def assets_instruments(asset_class: str):
        return get_instruments_by_class(asset_class)

    @router.get("/cloud/overview")
    def cloud_overview():
        return cloud_infrastructure.get_overview()

    @router.get("/cloud/providers/{provider_id}")
    def cloud_provider(provider_id: str):
        p = cloud_infrastructure.get_provider(provider_id)
        if not p:
            return JSONResponse({"error": "Provider not found"}, status_code=404)
        return p

    @router.get("/cloud/providers/{provider_id}/storage")
    def cloud_provider_storage(provider_id: str):
        return cloud_infrastructure.list_buckets(provider_id)

    @router.get("/cloud/providers/{provider_id}/loadbalancers")
    def cloud_provider_lb(provider_id: str):
        return cloud_infrastructure.list_load_balancers(provider_id)

    @router.get("/cloud/providers/{provider_id}/cdn")
    def cloud_provider_cdn(provider_id: str):
        return cloud_infrastructure.get_cdn(provider_id)

    @router.post("/cloud/providers/{provider_id}/scale")
    def cloud_provider_scale(provider_id: str, body: dict):
        return cloud_infrastructure.scale_provider(provider_id, _qint(body.get("delta"), 1))

    @router.post("/cloud/providers/{provider_id}/autoscaling")
    def cloud_provider_autoscaling(provider_id: str, body: dict):
        return cloud_infrastructure.set_auto_scaling(provider_id, body)

    @router.post("/cloud/providers/{provider_id}/failure")
    def cloud_provider_failure(provider_id: str):
        return cloud_infrastructure.simulate_failure(provider_id)

    @router.get("/cloud/backups")
    def cloud_backups():
        return cloud_infrastructure.list_backups()

    @router.post("/cloud/backups")
    def cloud_backups_post(body: dict):
        provider = body.get("provider")
        if not provider:
            providers = cloud_infrastructure.get_overview().get("providers") or []
            provider = providers[0]["provider"] if providers else None
        b = cloud_infrastructure.create_backup(provider)
        if not b:
            return JSONResponse({"error": "Provider not found"}, status_code=404)
        return b

    @router.post("/cloud/backups/{backup_id}/restore")
    def cloud_backup_restore(backup_id: str):
        return cloud_infrastructure.restore_backup(backup_id)

    @router.get("/cloud/restores")
    def cloud_restores():
        return cloud_infrastructure.list_restores()

    @router.get("/devops/overview")
    def devops_overview():
        return devops_manager.get_overview()

    @router.get("/devops/k8s")
    def devops_k8s():
        return devops_manager.get_k8s_state()

    @router.get("/devops/releases")
    def devops_releases():
        return devops_manager.list_releases()

    @router.post("/devops/releases")
    def devops_releases_post(body: dict):
        return devops_manager.create_release(body)

    @router.post("/devops/pipelines/{pipeline_id}/run")
    def devops_pipeline_run(pipeline_id: str):
        return devops_manager.run_pipeline(pipeline_id)

    @router.post("/devops/pipelines/{pipeline_id}/toggle")
    def devops_pipeline_toggle(pipeline_id: str, body: dict):
        return devops_manager.toggle_pipeline(pipeline_id, body.get("enabled"))

    @router.post("/devops/pipelines/run-all")
    def devops_pipelines_run_all():
        return devops_manager.run_all()

    @router.get("/production/overview")
    def production_overview():
        return production_readiness.get_overall()

    @router.get("/production/checklist")
    def production_checklist():
        return production_readiness.get_checklist()

    @router.post("/production/checklist/{item_id}")
    def production_checklist_item(item_id: str, body: dict):
        return production_readiness.update_checklist_item(item_id, body.get("completed"), body.get("notes"))

    @router.post("/production/stress-test")
    async def production_stress(body: dict):
        return await production_readiness.run_stress_test(body)

    @router.post("/production/load-test")
    async def production_load(body: dict):
        return await production_readiness.run_load_test(body)

    @router.get("/production/tests")
    def production_tests():
        return production_readiness.list_tests()

    @router.post("/production/security-scan")
    def production_security_scan():
        return production_readiness.run_security_hardening_scan()

    @router.get("/production/security-scans")
    def production_security_scans():
        return production_readiness.list_security_scans()

    @router.get("/production/performance")
    def production_performance():
        return production_readiness.performance_optimization()

    @router.post("/production/performance/{opt_id}/apply")
    def production_performance_apply(opt_id: str):
        return production_readiness.apply_optimization(opt_id)

    @router.get("/production/high-availability")
    def production_ha():
        return production_readiness.get_high_availability()

    @router.post("/production/failover")
    def production_failover(body: dict):
        return production_readiness.trigger_failover(body.get("target"))

    @router.get("/production/disaster-recovery")
    def production_dr():
        return production_readiness.disaster_recovery_plan()

    @router.post("/production/dr-drill")
    def production_dr_drill():
        return production_readiness.run_dr_drill()

    @router.post("/production/audit")
    def production_audit():
        return production_readiness.run_audit()

    @router.get("/production/audits")
    def production_audits():
        return production_readiness.list_audits()

    @router.get("/validation/suites")
    def validation_suites():
        return validation_manager.get_suites()

    @router.post("/validation/run/{suite_id}")
    async def validation_run(suite_id: str):
        return await validation_manager.run_suite(suite_id)

    @router.post("/validation/run-all")
    async def validation_run_all():
        return await validation_manager.run_all_suites()

    @router.get("/validation/runs")
    def validation_runs():
        return validation_manager.list_runs()

    @router.get("/validation/certification")
    async def validation_certification():
        return await validation_manager.get_certification()

    @router.get("/system/security")
    def system_security():
        return {
            "authEnabled": settings.security["authEnabled"],
            "rateLimit": rate_limiter.snapshot(),
            "headers": {"helmet": True, "cors": "enabled"},
        }

    @router.get("/system/analytics")
    def system_analytics(request: Request):
        return api_analytics.summary(_qint(request.query_params.get("limit"), 20))

    @router.get("/system/idempotency/status")
    def system_idempotency_status():
        return {"enabled": True, "ttlSeconds": idempotency_store.ttl_seconds}

    return router


_START = time.time()
