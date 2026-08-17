"""Additive API router for the AI provider clients.

Mounted alongside the main router at /api. Provides provider status listing
and a manual reasoning entry point without touching existing routes.
"""
import time

from fastapi import APIRouter

from ..modules.ai.clients import LLMError, ai_providers_status, run_llm_reasoning


def create_ai_router():
    router = APIRouter()

    @router.get("/ai/providers")
    def providers_list():
        return {"status": "ok", "data": ai_providers_status(), "timestamp": int(time.time() * 1000)}

    @router.post("/ai/reason")
    def reason(context: dict):
        try:
            result = run_llm_reasoning(context or {})
        except LLMError as exc:
            return {"status": "error", "error": str(exc), "timestamp": int(time.time() * 1000)}
        return {"status": "ok", "data": result, "timestamp": int(time.time() * 1000)}

    return router
