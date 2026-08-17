"""Agent Status API router (additive).

Endpoints for the Agent Command Center frontend. All data is read-only: the
tracker state is fed by the passive event observer in ``agent_status_tracker.py``
and the model mapping is read from the existing registry / provider status
surfaces without modifying any of them.
"""
import time

from fastapi import APIRouter

from ...foundation.logger import logger
from .agent_status_tracker import agent_status_tracker


def create_agent_status_router():
    router = APIRouter()

    @router.get("/pro/agents/status")
    def agents_status():
        statuses = agent_status_tracker.get_all_statuses()
        return {"timestamp": int(time.time() * 1000), "agents": statuses}

    @router.get("/pro/agents/history/{agent_id}")
    def agents_history(agent_id: str, limit: int = 20):
        rows = agent_status_tracker.get_history(agent_id, limit=max(1, min(limit, 100)))
        return {"agent_id": agent_id, "history": rows}

    @router.get("/pro/agents/models-in-use")
    def agents_models_in_use():
        return _models_in_use()

    return router


def _safe(fn, default):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - read-only probes must never crash
        logger.warn(f"models-in-use probe failed: {exc}")
        return default


def _models_in_use():
    """Per-agent -> provider/model mapping (read-only)."""
    active_provider = None
    providers = []
    status = _safe(lambda: _providers_status(), {"providers": [], "available": False})
    for p in status.get("providers") or []:
        providers.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "model": p.get("model"),
            "enabled": bool(p.get("enabled", True)),
        })
        if active_provider is None and p.get("enabled", True):
            active_provider = p

    custom = _safe(lambda: _custom_agents(), [])

    def _resolve(agent_id, name):
        if active_provider:
            return {
                "agent_id": agent_id,
                "name": name,
                "provider": active_provider.get("id"),
                "providerName": active_provider.get("name"),
                "model": active_provider.get("model"),
                "source": "managed",
            }
        return {
            "agent_id": agent_id,
            "name": name,
            "provider": "local-fallback",
            "providerName": "Local / Rule-Based",
            "model": "local-heuristic",
            "source": "local",
        }

    agents = []
    seen = set()
    for record in agent_status_tracker.get_all_statuses():
        aid = record.get("agent_id")
        if aid in seen:
            continue
        seen.add(aid)
        agents.append(_resolve(aid, record.get("name") or aid))

    for ca in custom:
        cid = ca.get("id")
        if cid in seen:
            continue
        seen.add(cid)
        agents.append({
            "agent_id": cid,
            "name": ca.get("name") or "Custom Agent",
            "provider": ca.get("provider_type") or "free_local",
            "providerName": (ca.get("provider_type") or "free_local"),
            "model": ca.get("model_name") or "default",
            "source": "custom",
        })

    champion = _safe(lambda: _champion_model(), None)

    return {
        "timestamp": int(time.time() * 1000),
        "agents": agents,
        "providers": providers,
        "championModel": champion,
        "cost": _safe(lambda: _cost_status(), {"enabled": False, "providers": {}}),
    }


def _providers_status():
    from ..ai.clients import ai_providers_status

    return ai_providers_status()


def _custom_agents():
    from .consensus import custom_agent_registry

    return custom_agent_registry.list()


def _champion_model():
    from .model_registry import model_registry, CHAMPION

    rows = model_registry.list_models(status=CHAMPION)
    if not rows:
        return None
    return {
        "name": rows[0].get("name"),
        "version": rows[0].get("version"),
        "model": (rows[0].get("metadata") or {}).get("model"),
    }


def _cost_status():
    from .provider_extensions import cost_tracker

    status = cost_tracker.status()
    total_cost = 0.0
    total_tokens = 0
    for row in (status.get("providers") or {}).values():
        total_cost += row.get("estimatedCostUsd") or 0.0
        total_tokens += row.get("totalTokens") or 0
    status["totalEstimatedCostUsd"] = round(total_cost, 4)
    status["totalTokens"] = total_tokens
    return status
