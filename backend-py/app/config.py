"""Configuration for the QuantOS AI backend.

Port of the Node `config/config.js` plus the settings surface mandated by the
master prompt (settings.py spec). Env-var fallback behavior from the JS config
is preserved; spec settings default values are honored.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DATA_DIR = ROOT_DIR / "backend" / "data"

load_dotenv(ROOT_DIR / ".env")


def _env(key: str, fallback):
    return os.environ.get(key, fallback)


def _env_int(key: str, fallback: int) -> int:
    try:
        return int(_env(key, fallback))
    except (TypeError, ValueError):
        return fallback


def _env_bool(key: str, fallback: bool) -> bool:
    val = _env(key, fallback)
    if isinstance(val, bool):
        return val
    return str(val).lower() in ("1", "true", "yes", "on")


class Settings:
    # ---- App ----
    APP_NAME: str = _env("APP_NAME", "QuantOS AI")
    APP_VERSION: str = _env("APP_VERSION", "1.0.0")
    ENVIRONMENT: str = _env("ENVIRONMENT", _env("NODE_ENV", "production"))
    DEBUG: bool = _env_bool("DEBUG", False)
    LOG_LEVEL: str = _env("LOG_LEVEL", "INFO")
    PORT: int = _env_int("PORT", 3001)
    HOST: str = _env("HOST", "0.0.0.0")
    ROOT_DIR: Path = ROOT_DIR
    DATA_DIR: str = _env("DATA_DIR", str(BACKEND_DATA_DIR))
    API_PREFIX: str = "/api"

    # ---- Persistence (JSON file store; Postgres is a later swap) ----
    DATABASE_URL: str = _env("DATABASE_URL", "")
    REDIS_URL: str = _env("REDIS_URL", "")
    # Postgres is used when DATABASE_URL is set; otherwise the JSON store remains.
    POSTGRES_ENABLED: bool = _env_bool("POSTGRES_ENABLED", False)
    DB_POOL_SIZE: int = _env_int("DB_POOL_SIZE", 10)
    DB_MAX_OVERFLOW: int = _env_int("DB_MAX_OVERFLOW", 20)

    # ---- Celery (new persistence/queue layer; Redis-backed) ----
    CELERY_ENABLED: bool = _env_bool("CELERY_ENABLED", False)
    CELERY_BROKER_URL: str = _env("CELERY_BROKER_URL", "")
    CELERY_RESULT_BACKEND: str = _env("CELERY_RESULT_BACKEND", "")
    CELERY_BEAT_SCHEDULE_ENABLED: bool = _env_bool("CELERY_BEAT_SCHEDULE_ENABLED", True)
    NEWS_POLL_INTERVAL_SECONDS: int = _env_int("NEWS_POLL_INTERVAL_SECONDS", 60)
    LEARNING_DAILY_INTERVAL_SECONDS: int = _env_int("LEARNING_DAILY_INTERVAL_SECONDS", 86400)

    # ---- Custom agent API key encryption (Fernet) ----
    CRYPTO_KEY: str = _env("CRYPTO_KEY", "")

    # ---- Auth ----
    JWT_SECRET: str = _env("JWT_SECRET", "zz-quantos-dev-secret-change-me")
    JWT_EXPIRES_IN: str = _env("JWT_EXPIRES_IN", "24h")
    JWT_EXPIRES_SECONDS: int = 24 * 60 * 60
    # Spec aliases (settings.py field names) mapped additively onto the same source.
    JWT_SECRET_KEY: str = _env("JWT_SECRET_KEY", JWT_SECRET)
    JWT_ALGORITHM: str = _env("JWT_ALGORITHM", "HS256")
    JWT_EXPIRE_MINUTES: int = _env_int("JWT_EXPIRE_MINUTES", 24 * 60)

    # ---- Rate limit ----
    RATE_LIMIT_WINDOW_MS: int = _env_int("RATE_LIMIT_WINDOW_MS", 60000)
    RATE_LIMIT_MAX: int = _env_int("RATE_LIMIT_MAX", 300)

    # ---- Security ----
    AUTH_REQUIRED: bool = _env_bool("AUTH_REQUIRED", False)

    # ---- AI providers ----
    AI_PROVIDER: str = _env("AI_PROVIDER", "ollama")
    AI_MODEL: str = _env("AI_MODEL", "deepseek-r1:distill-qwen-32b")
    AI_FALLBACK_MODEL: str = _env("AI_FALLBACK_MODEL", "qwen2.5:32b")
    AI_BASE_URL: str = _env("AI_BASE_URL", "http://localhost:11434")
    AI_LOCAL_PATH: str = _env("AI_LOCAL_PATH", str(ROOT_DIR / "models"))
    AI_MAX_RETRIES: int = _env_int("AI_MAX_RETRIES", 3)
    AI_TIMEOUT_SECONDS: int = _env_int("AI_TIMEOUT_SECONDS", 120)
    AI_CIRCUIT_BREAKER_FAILURES: int = _env_int("AI_CIRCUIT_BREAKER_FAILURES", 5)
    AI_CIRCUIT_BREAKER_RESET_SECONDS: int = _env_int("AI_CIRCUIT_BREAKER_RESET_SECONDS", 60)
    AI_RATE_LIMIT_RPM: int = _env_int("AI_RATE_LIMIT_RPM", 30)
    # Additional provider keys come from user-facing env vars only (never platform keys).
    USER_LLM_API_KEY: str = _env("USER_LLM_API_KEY", "")
    USER_LLM_BASE_URL: str = _env("USER_LLM_BASE_URL", "")
    USER_LLM_MODEL: str = _env("USER_LLM_MODEL", "deepseek-chat")
    USER_LLM_ANTHROPIC_API_KEY: str = _env("USER_LLM_ANTHROPIC_API_KEY", "")
    USER_LLM_GEMINI_API_KEY: str = _env("USER_LLM_GEMINI_API_KEY", "")
    USER_LLM_OPENROUTER_API_KEY: str = _env("USER_LLM_OPENROUTER_API_KEY", "")
    USER_LLM_OPENROUTER_MODEL: str = _env("USER_LLM_OPENROUTER_MODEL", "deepseek/deepseek-chat")
    USER_LLM_GLM_API_KEY: str = _env("USER_LLM_GLM_API_KEY", "")
    USER_LLM_GLM_MODEL: str = _env("USER_LLM_GLM_MODEL", "glm-4-plus")
    # Batch 02 additive providers (user-facing keys only, never platform keys).
    USER_LLM_XAI_API_KEY: str = _env("USER_LLM_XAI_API_KEY", "")
    USER_LLM_XAI_MODEL: str = _env("USER_LLM_XAI_MODEL", "grok-3")
    USER_LLM_DASHSCOPE_API_KEY: str = _env("USER_LLM_DASHSCOPE_API_KEY", "")
    USER_LLM_DASHSCOPE_MODEL: str = _env("USER_LLM_DASHSCOPE_MODEL", "qwen-plus")
    USER_LLM_DASHSCOPE_CN_API_KEY: str = _env("USER_LLM_DASHSCOPE_CN_API_KEY", "")
    USER_LLM_DASHSCOPE_CN_MODEL: str = _env("USER_LLM_DASHSCOPE_CN_MODEL", "qwen-plus")
    USER_LLM_ZHIPU_API_KEY: str = _env("USER_LLM_ZHIPU_API_KEY", "")
    USER_LLM_ZHIPU_MODEL: str = _env("USER_LLM_ZHIPU_MODEL", "glm-4.6")
    USER_LLM_MINIMAX_API_KEY: str = _env("USER_LLM_MINIMAX_API_KEY", "")
    USER_LLM_MINIMAX_MODEL: str = _env("USER_LLM_MINIMAX_MODEL", "MiniMax-Text-01")
    USER_LLM_MINIMAX_CN_API_KEY: str = _env("USER_LLM_MINIMAX_CN_API_KEY", "")
    USER_LLM_MINIMAX_CN_MODEL: str = _env("USER_LLM_MINIMAX_CN_MODEL", "MiniMax-Text-01")
    USER_LLM_NVIDIA_API_KEY: str = _env("USER_LLM_NVIDIA_API_KEY", "")
    USER_LLM_NVIDIA_MODEL: str = _env("USER_LLM_NVIDIA_MODEL", "deepseek-ai/deepseek-r1")
    # Alpha Vantage market data (non-LLM, additive quote feed).
    ALPHA_VANTAGE_API_KEY: str = _env("ALPHA_VANTAGE_API_KEY", "")
    USER_LLM_LMSTUDIO_BASE_URL: str = _env("USER_LLM_LMSTUDIO_BASE_URL", "")
    USER_LLM_LMSTUDIO_MODEL: str = _env("USER_LLM_LMSTUDIO_MODEL", "local-model")
    USER_LLM_HUGGINGFACE_API_KEY: str = _env("USER_LLM_HUGGINGFACE_API_KEY", "")
    USER_LLM_HUGGINGFACE_BASE_URL: str = _env("USER_LLM_HUGGINGFACE_BASE_URL", "")
    USER_LLM_HUGGINGFACE_MODEL: str = _env("USER_LLM_HUGGINGFACE_MODEL", "microsoft/Phi-3-mini-4k-instruct")
    USER_LLM_CUSTOM_BASE_URL: str = _env("USER_LLM_CUSTOM_BASE_URL", "")
    USER_LLM_CUSTOM_API_KEY: str = _env("USER_LLM_CUSTOM_API_KEY", "")
    USER_LLM_CUSTOM_MODEL: str = _env("USER_LLM_CUSTOM_MODEL", "model")
    USER_LLM_AZURE_API_KEY: str = _env("USER_LLM_AZURE_API_KEY", "")
    USER_LLM_AZURE_ENDPOINT: str = _env("USER_LLM_AZURE_ENDPOINT", "")
    USER_LLM_AZURE_DEPLOYMENT: str = _env("USER_LLM_AZURE_DEPLOYMENT", "gpt-4o")
    USER_LLM_AZURE_API_VERSION: str = _env("USER_LLM_AZURE_API_VERSION", "2024-06-01")
    USER_LLM_AZURE_MODEL: str = _env("USER_LLM_AZURE_MODEL", "")
    AI_STREAMING: bool = _env_bool("AI_STREAMING", False)
    AI_TOKEN_BUDGET_PER_CALL: int = _env_int("AI_TOKEN_BUDGET_PER_CALL", 2000)
    AI_COST_TRACKING: bool = _env_bool("AI_COST_TRACKING", True)
    AI_PROVIDER_PRIORITY: str = _env("AI_PROVIDER_PRIORITY", "")

    # ---- Social sentiment collectors (Feature 2, user-facing config only) ----
    SOCIAL_STOCKTWITS_ENABLED: bool = _env_bool("SOCIAL_STOCKTWITS_ENABLED", False)
    SOCIAL_STOCKTWITS_BASE_URL: str = _env("SOCIAL_STOCKTWITS_BASE_URL", "https://api.stocktwits.com/api/2")
    SOCIAL_STOCKTWITS_TOKEN: str = _env("SOCIAL_STOCKTWITS_TOKEN", "")
    SOCIAL_POLL_TIMEOUT_SECONDS: int = _env_int("SOCIAL_POLL_TIMEOUT_SECONDS", 10)
    SOCIAL_POLL_LIMIT: int = _env_int("SOCIAL_POLL_LIMIT", 20)

    # ---- Daily report delivery (Feature 4, additive) ----
    # Each channel is independently toggled and fails safe: when credentials
    # are missing the delivery is recorded as "pending" and skipped silently.
    REPORT_DELIVERY_INTERVAL_SECONDS: int = _env_int("REPORT_DELIVERY_INTERVAL_SECONDS", 86400)
    REPORT_DELIVERY_EMAIL_ENABLED: bool = _env_bool("REPORT_DELIVERY_EMAIL_ENABLED", True)
    REPORT_DELIVERY_WHATSAPP_ENABLED: bool = _env_bool("REPORT_DELIVERY_WHATSAPP_ENABLED", True)
    REPORT_DELIVERY_TELEGRAM_ENABLED: bool = _env_bool("REPORT_DELIVERY_TELEGRAM_ENABLED", True)
    SMTP_HOST: str = _env("SMTP_HOST", "")
    SMTP_PORT: int = _env_int("SMTP_PORT", 587)
    SMTP_USER: str = _env("SMTP_USER", "")
    SMTP_PASSWORD: str = _env("SMTP_PASSWORD", "")
    SMTP_STARTTLS: bool = _env_bool("SMTP_STARTTLS", True)
    EMAIL_FROM: str = _env("EMAIL_FROM", "")
    EMAIL_TO: str = _env("EMAIL_TO", "")
    EMAIL_SUBJECT_PREFIX: str = _env("EMAIL_SUBJECT_PREFIX", "QuantOS AI")


    # ---- Trading / risk ----
    TRADING_MODE: str = _env("TRADING_MODE", "analysis")
    CONFIDENCE_THRESHOLD: float = _env_int("CONFIDENCE_THRESHOLD", 90) / 100.0
    CONFIDENCE_SUGGEST_THRESHOLD: float = _env_int("CONFIDENCE_SUGGEST_THRESHOLD", 70) / 100.0
    AUTO_CLOSE_CONFIDENCE_THRESHOLD: float = _env_int("AUTO_CLOSE_CONFIDENCE_THRESHOLD", 70) / 100.0
    EMERGENCY_CLOSE_CONFIDENCE_THRESHOLD: float = _env_int("EMERGENCY_CLOSE_CONFIDENCE_THRESHOLD", 50) / 100.0
    MAX_RISK_PER_TRADE: float = _env_int("MAX_RISK_PER_TRADE", 100) / 100.0
    DAILY_LOSS_LIMIT: float = _env_int("DAILY_LOSS_LIMIT", 100)
    MAX_TOTAL_EXPOSURE: float = _env_int("MAX_TOTAL_EXPOSURE", 30) / 100.0
    WEEKLY_LOSS_LIMIT: float = _env_int("WEEKLY_LOSS_LIMIT", 300)
    MAX_CONSECUTIVE_LOSSES: int = _env_int("MAX_CONSECUTIVE_LOSSES", 5)
    MAX_DRAWDOWN_PERCENT: float = _env_int("MAX_DRAWDOWN_PERCENT", 15) / 100.0
    EMERGENCY_EQUITY_THRESHOLD: float = _env_int("EMERGENCY_EQUITY_THRESHOLD", 80) / 100.0
    BREAK_EVEN_PIPS: int = _env_int("BREAK_EVEN_PIPS", 15)
    TRAILING_STOP_METHOD: str = _env("TRAILING_STOP_METHOD", "atr")
    TRAILING_ATR_MULTIPLIER: float = _env_int("TRAILING_ATR_MULTIPLIER", 200) / 100.0
    PARTIAL_CLOSE_TP1_PERCENT: float = _env_int("PARTIAL_CLOSE_TP1_PERCENT", 30) / 100.0
    PARTIAL_CLOSE_TP2_PERCENT: float = _env_int("PARTIAL_CLOSE_TP2_PERCENT", 30) / 100.0
    DEFAULT_RR_RATIO: float = _env_int("DEFAULT_RR_RATIO", 200) / 100.0
    MAX_SPREAD_PIPS: int = _env_int("MAX_SPREAD_PIPS", 3)
    MAX_SLIPPAGE_PIPS: int = _env_int("MAX_SLIPPAGE_PIPS", 2)
    STALE_DATA_THRESHOLD_SECONDS: int = _env_int("STALE_DATA_THRESHOLD_SECONDS", 30)
    MAX_TICK_AGE_SECONDS: int = _env_int("MAX_TICK_AGE_SECONDS", 10)
    MIN_NEWS_CONFIDENCE: float = _env_int("MIN_NEWS_CONFIDENCE", 70) / 100.0
    MIN_DECISION_CONFIDENCE: float = _env_int("MIN_DECISION_CONFIDENCE", 90) / 100.0
    REANALYSIS_INTERVAL_SECONDS: int = _env_int("REANALYSIS_INTERVAL_SECONDS", 900)
    REANALYSIS_ON_NEWS: bool = _env_bool("REANALYSIS_ON_NEWS", True)
    SUGGESTED_TRADE_EXPIRY_SECONDS: int = _env_int("SUGGESTED_TRADE_EXPIRY_SECONDS", 3600)

    # ---- MT5 ----
    MT5_ENABLED: str = _env("MT5_ENABLED", "demo")
    MT5_LOGIN: str = _env("MT5_LOGIN", "")
    MT5_PASSWORD: str = _env("MT5_PASSWORD", "")
    MT5_SERVER: str = _env("MT5_SERVER", "")
    MT5_PATH: str = _env("MT5_PATH", "")
    MT5_HOST: str = _env("MT5_HOST", "127.0.0.1")
    MT5_PORT: int = _env_int("MT5_PORT", 443)
    MT5_BRIDGE_URL: str = _env("MT5_BRIDGE_URL", "")

    # ---- Binance ----
    BINANCE_API_KEY: str = _env("BINANCE_API_KEY", "")
    BINANCE_SECRET: str = _env("BINANCE_SECRET", "")

    # ---- Scheduler ----
    SCHEDULER_TZ: str = _env("SCHEDULER_TZ", "UTC")

    # ---- Providers ----
    @property
    def providers(self):
        mt5 = None
        if self.MT5_ENABLED != "off":
            mt5 = {
                "mode": self.MT5_ENABLED,
                "host": self.MT5_HOST,
                "port": self.MT5_PORT,
                "login": self.MT5_LOGIN,
                "password": self.MT5_PASSWORD,
                "bridgeUrl": self.MT5_BRIDGE_URL,
            }
        binance = None
        if self.BINANCE_API_KEY:
            binance = {"apiKey": self.BINANCE_API_KEY, "secret": self.BINANCE_SECRET}
        return {"mt5": mt5, "binance": binance}

    @property
    def ai(self):
        return {
            "provider": self.AI_PROVIDER,
            "model": self.AI_MODEL,
            "fallbackModel": self.AI_FALLBACK_MODEL,
            "baseUrl": self.AI_BASE_URL,
            "localPath": self.AI_LOCAL_PATH,
            "maxRetries": self.AI_MAX_RETRIES,
            "timeoutSeconds": self.AI_TIMEOUT_SECONDS,
            "circuitBreaker": {
                "failures": self.AI_CIRCUIT_BREAKER_FAILURES,
                "resetSeconds": self.AI_CIRCUIT_BREAKER_RESET_SECONDS,
            },
            "rateLimitRpm": self.AI_RATE_LIMIT_RPM,
            "streaming": self.AI_STREAMING,
            "costTracking": self.AI_COST_TRACKING,
            "tokenBudgetPerCall": self.AI_TOKEN_BUDGET_PER_CALL,
            "priority": self.AI_PROVIDER_PRIORITY,
            "providers": {
                "openaiCompatible": {
                    "apiKey": self.USER_LLM_API_KEY,
                    "baseUrl": self.USER_LLM_BASE_URL,
                    "model": self.USER_LLM_MODEL,
                },
                "anthropic": {"apiKey": self.USER_LLM_ANTHROPIC_API_KEY},
                "gemini": {"apiKey": self.USER_LLM_GEMINI_API_KEY},
                "openrouter": {
                    "apiKey": self.USER_LLM_OPENROUTER_API_KEY,
                    "model": self.USER_LLM_OPENROUTER_MODEL,
                },
                "glm": {
                    "apiKey": self.USER_LLM_GLM_API_KEY,
                    "model": self.USER_LLM_GLM_MODEL,
                },
                "xai": {
                    "apiKey": self.USER_LLM_XAI_API_KEY,
                    "model": self.USER_LLM_XAI_MODEL,
                },
                "dashscope": {
                    "apiKey": self.USER_LLM_DASHSCOPE_API_KEY,
                    "model": self.USER_LLM_DASHSCOPE_MODEL,
                },
                "dashscope-cn": {
                    "apiKey": self.USER_LLM_DASHSCOPE_CN_API_KEY,
                    "model": self.USER_LLM_DASHSCOPE_CN_MODEL,
                },
                "zhipu": {
                    "apiKey": self.USER_LLM_ZHIPU_API_KEY,
                    "model": self.USER_LLM_ZHIPU_MODEL,
                },
                "minimax": {
                    "apiKey": self.USER_LLM_MINIMAX_API_KEY,
                    "model": self.USER_LLM_MINIMAX_MODEL,
                },
                "minimax-cn": {
                    "apiKey": self.USER_LLM_MINIMAX_CN_API_KEY,
                    "model": self.USER_LLM_MINIMAX_CN_MODEL,
                },
                "nvidia": {
                    "apiKey": self.USER_LLM_NVIDIA_API_KEY,
                    "model": self.USER_LLM_NVIDIA_MODEL,
                },
                "azure": {
                    "apiKey": self.USER_LLM_AZURE_API_KEY,
                    "endpoint": self.USER_LLM_AZURE_ENDPOINT,
                    "deployment": self.USER_LLM_AZURE_DEPLOYMENT,
                    "apiVersion": self.USER_LLM_AZURE_API_VERSION,
                    "model": self.USER_LLM_AZURE_MODEL,
                },
            },
        }

    @property
    def rate_limit(self):
        return {"windowMs": self.RATE_LIMIT_WINDOW_MS, "max": self.RATE_LIMIT_MAX}

    @property
    def security(self):
        return {"authEnabled": self.AUTH_REQUIRED}


settings = Settings()
