"""Shared helpers for the quant_stats module (additive)."""
import numpy as np


def _py(value):
    """Numpy scalar -> python scalar (JSON safe, NaN/Inf -> None)."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(v) or np.isinf(v):
        return None
    return v


def _safe_series(values):
    """Coerce a list/array/None into a 1-D float numpy array."""
    if values is None:
        return np.array([], dtype=float)
    try:
        arr = np.asarray(values, dtype=float)
    except (TypeError, ValueError):
        return np.array([], dtype=float)
    return arr.reshape(-1)
