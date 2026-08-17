"""Derivatives intelligence (additive pro module, Task 1.7).

Endpoints (mounted under /api):
  - GET /api/pro/derivatives/options-chain/{symbol}
  - GET /api/pro/derivatives/unusual/{symbol}
  - GET /api/pro/derivatives/futures-curve/{symbol}
  - GET /api/pro/derivatives/summary/{symbol}

All endpoints degrade gracefully to a flagged simulator payload when no live
feed / API key is available — they never crash.
"""
