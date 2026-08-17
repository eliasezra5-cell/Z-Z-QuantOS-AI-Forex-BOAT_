"""Kronos candlestick forecasting engine (additive, lazy-loaded).

Wraps the NeoQuasar Kronos-mini foundation model (4.1M params) for
candlestick path forecasting. The ``model`` Python package that provides
``Kronos / KronosTokenizer / KronosPredictor`` ships with the official Kronos
repo (``shiyu-coder/Kronos``, MIT); it is fetched on first use (or pointed at
via ``KRONOS_REPO_PATH``) and imported lazily.

Graceful degradation: torch, the repo, the HF download or the prediction can
all be missing/unreachable in a sandboxed preview. Nothing here may crash the
app or block startup — every public call returns a clean
``{"status": "unavailable", ...}`` payload instead of raising.
"""
import os
import sys

from ...foundation.logger import logger

KRONOS_MODEL_ID = "NeoQuasar/Kronos-mini"
KRONOS_TOKENIZER_ID = "NeoQuasar/Kronos-Tokenizer-2k"
KRONOS_REPO_URL = "https://github.com/shiyu-coder/Kronos.git"
DEFAULT_HORIZON = 24
MIN_CANDLES = 64
MAX_CONTEXT = 1024
DEFAULT_SAMPLE_COUNT = 3
NEUTRAL_BAND_PCT = 0.20

_loaded = {"predictor": None, "error": None, "tried": False}


def _repo_path():
    """Locate a checkout of the official Kronos repo (the ``model`` package)."""
    explicit = os.environ.get("KRONOS_REPO_PATH", "").strip()
    for candidate in (explicit, os.path.join(os.environ.get("DATA_DIR", ""), "kronos_repo")):
        if candidate and os.path.isdir(os.path.join(candidate, "model")):
            return candidate
    from ...config import settings
    candidate = os.path.join(settings.DATA_DIR, "kronos_repo")
    if os.path.isdir(os.path.join(candidate, "model")):
        return candidate
    try:
        import subprocess
        subprocess.run(
            ["git", "clone", "--depth", "1", KRONOS_REPO_URL, candidate],
            check=True, capture_output=True, timeout=300,
        )
        if os.path.isdir(os.path.join(candidate, "model")):
            return candidate
    except Exception as exc:  # noqa: BLE001 - offline sandbox is fine
        logger.warn(f"kronos: repo fetch failed ({exc})")
    return None


def _ensure_predictor():
    """Lazy-load the Kronos predictor exactly once; never at app startup."""
    if _loaded["tried"]:
        return _loaded["predictor"], _loaded["error"]
    _loaded["tried"] = True
    try:
        import torch  # noqa: F401 - hard runtime dependency of the Kronos package
    except Exception as exc:  # noqa: BLE001
        _loaded["error"] = f"torch not installed: {exc}"
        return None, _loaded["error"]
    repo = _repo_path()
    if repo and repo not in sys.path:
        sys.path.insert(0, repo)
    try:
        from model import Kronos, KronosPredictor, KronosTokenizer
    except Exception as exc:  # noqa: BLE001
        _loaded["error"] = f"Kronos model package unavailable: {exc}"
        return None, _loaded["error"]
    try:
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        tokenizer = KronosTokenizer.from_pretrained(KRONOS_TOKENIZER_ID)
        kronos = Kronos.from_pretrained(KRONOS_MODEL_ID)
        _loaded["predictor"] = KronosPredictor(
            kronos, tokenizer, device=device, max_context=MAX_CONTEXT
        )
    except Exception as exc:  # noqa: BLE001 - HF download can fail offline
        _loaded["error"] = f"Kronos model load failed: {exc}"
        return None, _loaded["error"]
    return _loaded["predictor"], None


def _candles_to_frame(symbol, timeframe="H1", count=400):
    """Reuse the marketdata feed; return (df, source) or (None, source)."""
    try:
        from ...marketdata.engine import generate_candles
        candles = generate_candles(symbol, timeframe, count)
    except Exception as exc:  # noqa: BLE001 - feed is optional
        logger.warn(f"kronos: candle fetch failed ({exc})")
        return None, "unavailable"
    if not candles or len(candles) < MIN_CANDLES:
        return None, "insufficient_data"
    import pandas as pd
    df = pd.DataFrame([
        {
            "timestamps": c["time"],
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "volume": float(c.get("volume", 0)),
        }
        for c in candles
    ])
    df["timestamps"] = pd.to_datetime(df["timestamps"], unit="ms")
    return df, "live" if str(getattr(candles[0], "source", "")) else "feed"


def forecast(symbol="XAUUSD", horizon=DEFAULT_HORIZON, timeframe="H1"):
    """Forecast the next ``horizon`` candles for ``symbol`` with Kronos-mini.

    Reuses the existing marketdata candle feed. Returns either a successful
    ``{"status": "ok", ...}`` payload (forecast path + directional read) or a
    clean ``{"status": "unavailable", ...}`` payload.
    """
    symbol = str(symbol or "XAUUSD").upper()
    try:
        horizon = max(1, min(int(horizon), 256))
    except (TypeError, ValueError):
        horizon = DEFAULT_HORIZON

    predictor, err = _ensure_predictor()
    if predictor is None:
        return {
            "status": "unavailable", "symbol": symbol,
            "horizon": horizon, "error": err or "Kronos model unavailable",
        }

    df, source = _candles_to_frame(symbol, timeframe, count=400)
    if df is None or len(df) < MIN_CANDLES:
        return {
            "status": "unavailable", "symbol": symbol,
            "horizon": horizon, "error": f"insufficient OHLCV history ({source})",
        }

    try:
        import pandas as pd
        x_df = df[["open", "high", "low", "close"]].iloc[-MAX_CONTEXT:]
        x_ts = pd.Series(x_df.index.tolist(), index=x_df.index, name="timestamps")
        delta = x_df.index.to_series().diff().median()
        if pd.isna(delta) or delta.total_seconds() <= 0:
            delta = pd.Timedelta(hours=1)
        y_ts = pd.Series(
            [x_df.index[-1] + delta * (i + 1) for i in range(horizon)],
            name="timestamps",
        )
        pred_df = predictor.predict(
            df=x_df,
            x_timestamp=x_ts,
            y_timestamp=y_ts,
            pred_len=horizon,
            T=1.0,
            top_p=0.9,
            sample_count=DEFAULT_SAMPLE_COUNT,
            verbose=False,
        )
    except Exception as exc:  # noqa: BLE001 - inference must degrade cleanly
        logger.warn(f"kronos: prediction failed ({exc})")
        return {
            "status": "unavailable", "symbol": symbol,
            "horizon": horizon, "error": f"Kronos prediction failed: {exc}",
        }

    closes = [float(v) for v in pred_df["close"].tolist()]
    if not closes:
        return {
            "status": "unavailable", "symbol": symbol,
            "horizon": horizon, "error": "Kronos returned no forecast path",
        }
    expected_pct = (closes[-1] / closes[0] - 1.0) * 100.0
    direction = "neutral"
    if expected_pct > NEUTRAL_BAND_PCT:
        direction = "buy"
    elif expected_pct < -NEUTRAL_BAND_PCT:
        direction = "sell"
    confidence = max(0.0, min(0.9, abs(expected_pct) / 5.0 + 0.20))

    last_close = float(df["close"].iloc[-1])
    actual_path = [
        {"time": int(pd.Timestamp(t).timestamp() * 1000), "close": float(v)}
        for t, v in zip(df["timestamps"].tolist()[-horizon:], df["close"].tolist()[-horizon:])
    ]
    forecast_path = [
        {"time": int(pd.Timestamp(t).timestamp() * 1000), "close": v}
        for t, v in zip(pred_df.index.tolist(), closes)
    ]
    return {
        "status": "ok",
        "symbol": symbol,
        "horizon": horizon,
        "model": KRONOS_MODEL_ID,
        "source": source,
        "direction": direction,
        "confidence": round(confidence, 3),
        "expectedChangePct": round(expected_pct, 3),
        "lastClose": round(last_close, 5),
        "predictedClose": round(closes[-1], 5),
        "forecastPath": forecast_path,
        "actualPath": actual_path,
    }
