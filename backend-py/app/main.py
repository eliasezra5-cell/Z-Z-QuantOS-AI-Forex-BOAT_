"""FastAPI entrypoint for the QuantOS AI backend."""
import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .foundation.logger import logger
from .foundation.event_bus import init_events, event_bus
from .foundation.distributed_event_bus import init_distributed_event_bus
from .foundation.json_store import init_database
from .foundation.security import init_security, authenticate_request
from .foundation.cache import init_cache
from .foundation.queue import init_queues
from .foundation.workers import init_workers
from .foundation.scheduler import init_scheduler, scheduler
from .foundation.plugins import init_plugins
from .foundation.provider_framework import init_providers
from .foundation.feature_flags import init_feature_flags
from .foundation.monitoring import init_monitoring
from .foundation.rate_limit import rate_limiter
from .foundation.errors import AppError
from .foundation.middleware import QuantOSMiddleware

from .persistence import init_models as init_pg_models
from .foundation.redis_pubsub import init_redis_pubsub
from .modules.news.realtime.registry import init_realtime_news_collectors
from .modules.news.extra_sources import init_extra_news_sources
from .modules.ai.decision_pipeline import init_decision_pipeline
from .modules.execution.position_sync import init_position_sync
from .routes.api import create_api_router
from .routes.brain import create_brain_router
from .routes.ai import create_ai_router
from .routes.events import create_events_router
from .routes.v1 import create_v1_router
from .routes.integrations_ext import create_enterprise_integrations_router
from .routes.technical_pro import create_technical_pro_router
from .routes.quant_stats import create_quant_stats_router
from .routes.fixedincome import create_fixedincome_router
from .routes.fixedincome_engine import create_fixedincome_engine_router
from .routes.macro_extra import create_macro_extra_router
from .routes.institutional_flow import create_institutional_flow_router
from .routes.derivatives import create_derivatives_router
from .routes.prediction_markets import create_prediction_markets_router
from .routes.portfolio_optimizer import create_portfolio_optimizer_router
from .routes.forecast import create_forecast_router
from .routes.advanced_orders import create_advanced_orders_router
from .routes.backtest_tearsheet import create_backtest_tearsheet_router

from .modules.marketdata.engine import init_market_data, generate_market_data_loop
from .modules.news.engine import init_news_engine
from .modules.news.decay import init_news_decay_engine
from .modules.news.collectors import init_news_collectors
from .modules.economic.engine import init_economic_calendar
from .modules.economic.revisions import init_economic_revisions
from .modules.macro.engine import init_macro
from .modules.historical.engine import init_historical
from .modules.historical.memory import init_historical_memory
from .modules.ai.memory import init_vector_db
from .modules.ai.decision_center import init_decision_center
from .modules.ai.learning import init_learning
from .modules.ai.model_registry import init_model_registry
from .modules.risk.engine import init_risk_engine
from .modules.risk.analyzers import init_risk_analyzers
from .modules.portfolio.service import init_portfolio
from .modules.trading.engine import init_trading_engine
from .modules.reports.renderers import init_report_renderers
from .modules.alerts.service import init_alerts
from .modules.features.store import init_feature_store
from .modules.pipeline.manager import init_data_pipeline
from .modules.observability.init import init_observability
from .modules.integrations.service import init_integrations
from .modules.multiasset.overview import init_multi_asset
from .modules.research.lab import init_research_lab
from .modules.security.module import init_security_module
from .modules.security.hardening import init_security_hardening
from .modules.users.service import init_users
from .modules.admin.service import init_admin
from .modules.cloud.infrastructure import init_cloud_infrastructure
from .modules.devops.manager import init_devops
from .modules.production.readiness import init_production_readiness
from .modules.validation.system import init_validation
from .modules.websocket.hub import register_websocket
from .modules.mt5.adapter import init_mt5
from .modules.marketdata.instrument_specs import init_instrument_specs
from .modules.risk.capital_protection import init_capital_protection
from .modules.technical.volume_analysis import init_volume_analysis
from .modules.risk.deterministic import init_position_sizing
from .modules.validation.engine import init_validation_engine
from .modules.execution.modes import init_trading_modes
from .modules.execution.auto_controller import init_auto_trade_controller
from .modules.execution.profit_protection import init_profit_protection
from .modules.execution.thesis import init_thesis_and_opposite_news
from .modules.execution.mt5_safety import init_mt5_safety
from .modules.ai.consensus import init_dynamic_consensus
from .modules.ai.clients import init_ai_clients, ai_provider_manager
from .modules.ai.provider_extensions import init_provider_extensions, reorder_providers_by_priority
from .modules.ai.extra_providers import init_extra_providers
from .modules.marketdata.alphavantage import init_alphavantage_provider
from .modules.portfolio.performance import init_performance_analytics
from .modules.backtest.advanced import init_backtest_advanced
from .modules.execution.brain_monitor import init_brain_monitor
from .modules.execution.institutional_executor import init_institutional_executor
from .modules.risk.capital_guard import init_capital_guard
from .modules.risk.strict_risk_policy import init_strict_risk_policy
from .modules.ai.pattern_learning import init_pattern_learning
from .modules.ai.mistake_analysis import init_mistake_analyzer
from .modules.backtest.walk_forward_analysis import init_walk_forward_analysis
from .modules.integrations.telegram_bot import init_telegram_bot
from .modules.integrations.discord_client import init_discord_alerts
from .modules.integrations.email_bot import init_email_bot
from .modules.integrations.trade_reporter import init_trade_reporter
from .modules.integrations.tradingview_webhook import init_tradingview_webhook
from .modules.technical.smc_math import init_advanced_smc
from .modules.technical.dynamic_sltp import init_dynamic_sltp
from .modules.risk.quant_models import init_quant_risk_engine
from .modules.security.salted_api_keys import init_salted_api_keys
from .foundation.redis_rate_limit import init_redis_rate_limit, redis_limiter, check_request_limits
from .foundation.tracing import init_tracing, extract_correlation_id, set_correlation_id, get_correlation_id, start_span
from .modules.security.protections import init_protections, security_headers as security_headers_policy, csrf_enforcer
from .modules.ai.agent_status_router import create_agent_status_router


def _init_system():
    import asyncio

    init_tracing()
    init_events()
    init_database()
    asyncio.run(init_pg_models())
    init_redis_pubsub()
    init_distributed_event_bus()
    init_security()
    init_cache()
    init_queues()
    init_workers()
    init_scheduler()
    init_plugins()
    init_providers()
    init_feature_flags()
    init_monitoring()


def init_news_poll_loop():
    """Autonomous news polling background thread (no Celery required).

    This deployment runs no Celery worker/beat process, so the coded
    ``poll-news`` beat task never fires and news sources — RSS/web/X-Twitter
    and, most importantly, Telegram manual-forwarded messages — are never
    picked up automatically. Start a lightweight daemon thread (same pattern
    as trading_engine's monitor/reanalysis loops) that calls
    ``poll_all_collectors`` every ``NEWS_POLL_INTERVAL_SECONDS``. A failing
    cycle is logged and never kills the loop; a single source's fetch failure
    is already isolated inside ``collect_from_sources``.
    """
    import threading

    from .modules.news.realtime.registry import poll_all_collectors

    interval = max(10, int(settings.NEWS_POLL_INTERVAL_SECONDS or 60))

    def _news_poll_loop():
        while True:
            time.sleep(interval)
            try:
                import asyncio

                asyncio.run(poll_all_collectors())
            except Exception as exc:  # noqa: BLE001 - never let the loop die
                logger.error(f"news poll cycle failed: {exc}")

    threading.Thread(target=_news_poll_loop, daemon=True).start()
    logger.info(f"News poll loop started (interval={interval}s)")


def _init_modules():
    init_market_data()
    init_alphavantage_provider()
    init_instrument_specs()
    init_news_engine()
    init_news_decay_engine()
    init_news_collectors()
    init_realtime_news_collectors()
    init_extra_news_sources()
    init_news_poll_loop()
    import asyncio

    try:
        from .modules.news.seed_sources import seed_default_news_sources

        asyncio.run(seed_default_news_sources())
    except Exception as exc:  # noqa: BLE001 - seeding must never block boot
        logger.warn(f"Failed to seed default news sources at boot: {exc}")
    init_economic_calendar()
    init_economic_revisions()
    init_macro()
    init_historical()
    init_historical_memory()
    try:
        from .modules.historical.memory import seed_event_embeddings
        seed_event_embeddings()
    except Exception as exc:  # noqa: BLE001 - seeding must never block boot
        logger.warn(f"Failed to seed historical corpus at boot: {exc}")
    init_vector_db()
    init_decision_center()
    init_dynamic_consensus()
    init_ai_clients()
    init_provider_extensions()
    init_extra_providers()
    reorder_providers_by_priority(ai_provider_manager)
    init_learning()
    init_model_registry()
    init_risk_engine()
    init_risk_analyzers()
    init_position_sizing()
    init_capital_protection()
    init_volume_analysis()
    init_portfolio()
    init_performance_analytics()
    init_trading_engine()
    init_trading_modes()
    init_auto_trade_controller()
    init_profit_protection()
    init_thesis_and_opposite_news()
    init_mt5_safety()
    init_alerts()
    init_report_renderers()
    init_feature_store()
    init_data_pipeline()
    init_observability()
    init_integrations()
    init_multi_asset()
    init_research_lab()
    init_security_module()
    init_security_hardening()
    init_users()
    init_admin()
    init_cloud_infrastructure()
    init_devops()
    init_production_readiness()
    init_validation()
    init_validation_engine()
    init_backtest_advanced()
    init_brain_monitor()
    init_capital_guard()
    init_decision_pipeline()
    init_position_sync()
    init_institutional_executor()
    init_strict_risk_policy()
    init_pattern_learning()
    init_mistake_analyzer()
    init_walk_forward_analysis()
    init_telegram_bot()
    init_discord_alerts()
    init_email_bot()
    init_trade_reporter()
    init_tradingview_webhook()
    init_advanced_smc()
    init_dynamic_sltp()
    init_quant_risk_engine()
    init_salted_api_keys()
    init_redis_rate_limit()
    init_protections()
    try:
        from .tasks.daily_report_delivery import init_daily_report_delivery

        init_daily_report_delivery()
    except Exception as exc:  # noqa: BLE001 - scheduler registration must never block boot
        logger.warn(f"Failed to register daily report delivery job: {exc}")


def create_app() -> FastAPI:
    _init_system()
    _init_modules()
    generate_market_data_loop()
    init_mt5()

    app = FastAPI(title="ZZ_QuantOS AI BOAT Backend", version="1.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:"
        forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
        if request.url.scheme == "https" or forwarded_proto == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(
        QuantOSMiddleware,
        version="v1",
        supported_versions=["v1"],
    )

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        logger.info(f"{request.method} {request.url.path}")
        from .modules.observability.init import count_request
        count_request()
        response = await call_next(request)
        return response

    @app.middleware("http")
    async def trace_and_correlation(request: Request, call_next):
        set_correlation_id(extract_correlation_id(request.headers) or get_correlation_id())
        started = time.monotonic()
        with start_span(
            f"{request.method} {request.url.path}",
            attrs={
                "http.method": request.method,
                "http.target": request.url.path,
                "http.client.ip": request.client.host if request.client else None,
            },
        ):
            response = await call_next(request)
        latency_ms = round((time.monotonic() - started) * 1000, 2)
        from .modules.observability.init import record_api_latency
        record_api_latency(request.method, request.url.path, latency_ms, status=response.status_code)
        response.headers["X-Correlation-Id"] = get_correlation_id()
        response.headers["X-Trace-Id"] = get_correlation_id()
        response.headers["X-Request-Time-Ms"] = str(latency_ms)
        return response

    @app.middleware("http")
    async def rate_limit_and_auth(request: Request, call_next):
        if request.url.path.startswith(settings.API_PREFIX):
            key = request.client.host if request.client else "unknown"
            result = rate_limiter.check(key)
            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(rate_limiter.max)
            response.headers["X-RateLimit-Remaining"] = str(result["remaining"])
            response.headers["X-RateLimit-Reset"] = str(max(0, int((result["resetAt"] - time.time() * 1000) / 1000)))
            if not result["allowed"]:
                return JSONResponse({"error": {"code": "RATE_LIMITED", "message": "Too many requests, please slow down"}}, status_code=429)
            return response
        return await call_next(request)

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        user = authenticate_request(request)
        if user:
            request.state.user = user
        elif settings.AUTH_REQUIRED and request.url.path.startswith(settings.API_PREFIX) and request.url.path not in ("/api/auth/login", "/api/health", "/api/v1/integrations/whatsapp/webhook"):
            return JSONResponse({"error": {"code": "UNAUTHORIZED", "message": "Authentication required"}}, status_code=401)
        return await call_next(request)

    @app.middleware("http")
    async def redis_rate_limit_and_security_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(settings.API_PREFIX):
            result = check_request_limits(request)
            response.headers["X-RateLimit-Limit"] = str(result["limit"])
            response.headers["X-RateLimit-Remaining"] = str(result["remaining"])
            response.headers["X-RateLimit-Reset"] = str(max(0, int((result["resetAt"] - time.time() * 1000) / 1000)))
            if not result["allowed"]:
                return JSONResponse({"error": {"code": "RATE_LIMITED", "message": "Too many requests, please slow down"}}, status_code=429)
        forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
        is_secure = request.url.scheme == "https" or forwarded_proto == "https"
        for name, value in security_headers_policy(secure=is_secure).items():
            response.headers[name] = value
        return response

    from .routes.whatsapp_ext import create_whatsapp_router
    from .routes.mt5_ext import create_mt5_router

    # The connections routes must be registered before the generic api router so
    # that POST /integrations/connections/test is not shadowed by the wildcard
    # POST /integrations/{integration_id}/test route defined in api.py.
    app.include_router(create_whatsapp_router(), prefix=settings.API_PREFIX)
    app.include_router(create_mt5_router(), prefix=settings.API_PREFIX)
    app.include_router(create_api_router(), prefix=settings.API_PREFIX)
    app.include_router(create_brain_router(), prefix=settings.API_PREFIX)
    app.include_router(create_ai_router(), prefix=settings.API_PREFIX)
    app.include_router(create_events_router(), prefix=settings.API_PREFIX)
    app.include_router(create_v1_router(), prefix=settings.API_PREFIX)
    app.include_router(create_enterprise_integrations_router(), prefix=settings.API_PREFIX)
    app.include_router(create_agent_status_router(), prefix=settings.API_PREFIX)
    app.include_router(create_technical_pro_router(), prefix=settings.API_PREFIX)
    app.include_router(create_quant_stats_router(), prefix=settings.API_PREFIX)
    app.include_router(create_fixedincome_router(), prefix=settings.API_PREFIX)
    app.include_router(create_fixedincome_engine_router(), prefix=settings.API_PREFIX)
    app.include_router(create_macro_extra_router(), prefix=settings.API_PREFIX)
    app.include_router(create_institutional_flow_router(), prefix=settings.API_PREFIX)
    app.include_router(create_derivatives_router(), prefix=settings.API_PREFIX)
    app.include_router(create_prediction_markets_router(), prefix=settings.API_PREFIX)
    app.include_router(create_portfolio_optimizer_router(), prefix=settings.API_PREFIX)
    app.include_router(create_forecast_router(), prefix=settings.API_PREFIX)
    app.include_router(create_advanced_orders_router(), prefix=settings.API_PREFIX)
    app.include_router(create_backtest_tearsheet_router(), prefix=settings.API_PREFIX)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse({"error": {"code": exc.code, "message": str(exc)}}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled error on {request.method} {request.url.path}", {"error": str(exc)})
        from .modules.observability.init import count_error
        count_error()
        return JSONResponse({"error": {"code": "INTERNAL_ERROR", "message": str(exc)}}, status_code=500)

    register_websocket(app)

    @app.on_event("shutdown")
    def _shutdown():
        logger.info("Shutting down...")
        scheduler.stop_all()

    return app


app = create_app()
