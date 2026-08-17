"""New v1 API router for the Postgres/pgvector migration layer.

Additive: does not replace any existing route. Introduces:
- ``/api/agents``        CRUD for custom AI agents (persisted via repository)
- ``/api/news/sources``  CRUD for realtime news sources (persisted via repository)
- ``/api/decisions``     listing of persisted AI decisions
- ``/api/pipeline/analyze``  on-demand decision pipeline trigger

The router is mounted under ``settings.API_PREFIX`` (``/api``) only — the
``/api/v1/...`` form is served by ``QuantOSMiddleware``'s version rewrite
(routers stay mounted under ``/api``, do not remount). Clients should call the
canonical ``/api`` paths directly.
"""
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..foundation.logger import logger
from ..persistence import custom_agent_repository, decision_repository
from ..modules.ai.decision_pipeline import analyze_symbol_pipeline

router = APIRouter()


class CustomAgentIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    provider_type: str = Field("free_local", pattern="^(free_local|paid_openai|paid_anthropic|paid_gemini|paid_deepseek|custom_http|xai|dashscope|dashscope-cn|zhipu|minimax|minimax-cn|nvidia)$")
    model_name: str = Field("", max_length=120)
    system_prompt: str = Field("", max_length=8000)
    voting_weight: float = Field(0.10, ge=0.0, le=0.20)
    api_key: str = Field("", max_length=512)
    base_url: str = Field("", max_length=1000)
    enabled: bool = True
    template: str = ""


class NewsSourceIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    type: str = Field("rss", pattern="^(rss|telegram|telegram_channel|twitter|x_twitter|web|web_blog|website|financial_api|reddit)$")
    url: str = Field("", max_length=1000)
    config: dict = {}
    priority: int = Field(50, ge=0, le=100)
    enabled: bool = True


def _validate_weight(value: float) -> float:
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise HTTPException(status_code=422, detail="voting_weight must be a decimal number")
    if dec < 0 or dec > Decimal("0.2"):
        raise HTTPException(status_code=422, detail="voting_weight must be between 0 and 0.20")
    return float(dec)


@router.get("/agents")
async def list_agents():
    agents = await custom_agent_repository.list()
    for a in agents:
        a.pop("api_key_encrypted", None)
        a.pop("api_key", None)
    return {"agents": agents, "total": len(agents)}


@router.post("/agents")
async def create_agent(body: CustomAgentIn):
    weight = _validate_weight(body.voting_weight)
    data = {
        "name": body.name,
        "provider_type": body.provider_type,
        "model_name": body.model_name or (None if body.provider_type == "free_local" else "gpt-4o-mini"),
        "system_prompt": body.system_prompt,
        "voting_weight": weight,
        "api_key": body.api_key,
        "base_url": body.base_url,
        "enabled": body.enabled,
        "template": body.template,
    }
    agent = await custom_agent_repository.create(data)
    agent.pop("api_key_encrypted", None)
    agent.pop("api_key", None)
    return {"agent": agent}


@router.put("/agents/{agent_id}")
async def update_agent(agent_id: str, body: CustomAgentIn):
    patch = body.dict(exclude_unset=True)
    if "voting_weight" in patch:
        patch["voting_weight"] = _validate_weight(patch["voting_weight"])
    if "api_key" in patch:
        api_key = patch.pop("api_key")
        if api_key:
            patch["api_key"] = api_key
        else:
            patch.pop("api_key", None)
    agent = await custom_agent_repository.update(agent_id, patch)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent.pop("api_key_encrypted", None)
    agent.pop("api_key", None)
    return {"agent": agent}


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    removed = await custom_agent_repository.remove(agent_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"removed": agent_id}


@router.post("/news/sources")
async def create_news_source(body: NewsSourceIn):
    from ..persistence import news_repository

    config = dict(body.config or {})
    if body.type in ("x_twitter", "twitter"):
        from ..modules.news.engine import build_twitter_handles

        handles = build_twitter_handles(config.get("handles"), body.url)
        if handles:
            config["handles"] = handles
    elif body.url:
        if body.type in ("rss",):
            config.setdefault("feedUrls", config.get("feedUrls") or [body.url])
            config.setdefault("feeds", config.get("feeds") or [body.url])
        elif body.type in ("web", "web_blog", "website"):
            # A website/blog link can be either a feed (yields multiple
            # stories) or a single page. Register it under both keys; the web
            # collector tries feed parsing first and falls back to page
            # extraction automatically.
            config.setdefault("feedUrls", config.get("feedUrls") or [body.url])
            config.setdefault("urls", config.get("urls") or [body.url])
        else:
            config.setdefault("urls", config.get("urls") or [body.url])
    source = await news_repository.add_source({
        "name": body.name,
        "type": body.type,
        "config": config,
        "priority": body.priority,
        "enabled": body.enabled,
    })
    return {"source": source}


@router.put("/news/sources/{source_id}")
async def update_news_source(source_id: str, body: NewsSourceIn):
    from ..persistence import news_repository

    patch = body.dict(exclude_unset=True)
    source = await news_repository.update_source(source_id, patch)
    if source is None:
        raise HTTPException(status_code=404, detail="News source not found")
    return {"source": source}


@router.delete("/news/sources/{source_id}")
async def delete_news_source(source_id: str):
    from ..persistence import news_repository

    removed = await news_repository.remove_source(source_id)
    if not removed:
        raise HTTPException(status_code=404, detail="News source not found")
    return {"removed": source_id}


@router.get("/news/items")
async def list_news_items(limit: int = 50, category: str = None, source: str = None):
    from ..persistence import news_repository

    items = await news_repository.list_items(
        limit=min(max(limit, 1), 200),
        category=category,
        source=source,
    )
    return {"items": items, "total": len(items)}


@router.get("/decisions")
async def list_decisions(symbol: str = None, limit: int = 50):
    items = await decision_repository.list(
        limit=min(max(limit, 1), 200),
        symbol=(symbol or "").upper() or None,
    )
    return {"decisions": items, "total": len(items)}


@router.post("/pipeline/analyze")
async def analyze_pipeline(symbol: str = "XAUUSD"):
    decision = await analyze_symbol_pipeline(symbol)
    return {"decision": decision}


def create_v1_router() -> APIRouter:
    return router
