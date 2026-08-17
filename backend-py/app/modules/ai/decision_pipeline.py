"""Institutional AI Decision Pipeline (5 agents + custom agents, asyncio.gather).

Triggered by a news event (``news:processed``) or by explicit request. Builds
context once, runs all agents in parallel via ``asyncio.gather`` (each agent
autonomously fetches its own data), computes the strict 80/20 consensus,
persists the decision, publishes ``AIDecisionMade`` to the Redis Streams bus
and feeds the auto-trade controller for the 90/70/<70 execution gates.
"""
import asyncio
import queue
import threading
import time
import uuid

from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.distributed_event_bus import distributed_event_bus
from ...foundation.json_store import db
from ...persistence import decision_repository, custom_agent_repository
from ..news.engine import get_news
from ..marketdata.engine import generate_candles, get_quote, get_instrument
from .agents import (
    NewsAnalysisAgent,
    HistoricalPatternAgent,
    MacroAnalysisAgent,
    TechnicalExecutionAgent,
    RiskManagerAgent,
    CustomAgentRunner,
    BullResearcherAgent,
    BearResearcherAgent,
    SentimentAnalysisAgent,
    FundamentalsAnalysisAgent,
    InstitutionalProAgent,
    KronosForecastAgent,
)
from .consensus_v2 import compute_consensus
from .research_manager import research_manager

CORE_AGENT_IDS = ("news", "historical", "macro", "technical", "risk")


class DecisionPipeline:
    def __init__(self):
        self._news_agent = NewsAnalysisAgent()
        self._historical_agent = HistoricalPatternAgent()
        self._macro_agent = MacroAnalysisAgent()
        self._technical_agent = TechnicalExecutionAgent()
        self._risk_agent = RiskManagerAgent()
        self._bull_agent = BullResearcherAgent()
        self._bear_agent = BearResearcherAgent()
        self._sentiment_agent = SentimentAnalysisAgent()
        self._fundamentals_agent = FundamentalsAnalysisAgent()
        self._pro_agent = InstitutionalProAgent()
        self._kronos_agent = KronosForecastAgent()
        self._lock = threading.Lock()

    async def build_context(self, symbol="XAUUSD"):
        news = get_news({"limit": 10})
        quote = get_quote(symbol)
        ctx = {
            "symbol": symbol,
            "news": news,
            "quote": quote,
            "newsCount": len(news),
            "timestamp": int(time.time() * 1000),
        }
        try:
            from .conversation import preference_context

            ctx["userPreferences"] = preference_context()
        except Exception:  # noqa: BLE001 - preferences are optional context
            pass
        return ctx

    async def run_agents(self, context):
        """Run the 5 core agents + custom agents (social sentiment, fundamentals)
        + enabled user custom agents in parallel."""
        agents = [
            self._news_agent.run(context),
            self._historical_agent.run(context),
            self._macro_agent.run(context),
            self._technical_agent.run(context),
            self._risk_agent.run(context),
            self._sentiment_agent.run(context),
            self._fundamentals_agent.run(context),
            self._pro_agent.run(context),
            self._kronos_agent.run(context),
        ]
        # Dynamically load enabled custom agents from the repository.
        try:
            custom_agents = await custom_agent_repository.enabled_agents()
            for ca in custom_agents:
                agents.append(CustomAgentRunner(ca).run(context))
        except Exception as exc:  # noqa: BLE001 - custom agents are optional
            logger.warn(f"Custom agent load failed: {exc}")
        results = await asyncio.gather(*agents, return_exceptions=True)
        return [r for r in results if not isinstance(r, Exception)]

    async def _run_debate(self, symbol, ctx, results, persist=True):
        """Feature 1 — run bull + bear researchers and resolve into a rating."""
        try:
            core_results = [
                r.to_dict() for r in results
                if getattr(r, "agent_id", None) in CORE_AGENT_IDS
            ]
            debate_ctx = {**ctx, "core_results": core_results}
            bull, bear = await asyncio.gather(
                self._bull_agent.run(debate_ctx),
                self._bear_agent.run(debate_ctx),
                return_exceptions=True,
            )
            bull = None if isinstance(bull, Exception) else bull
            bear = None if isinstance(bear, Exception) else bear
            resolved = research_manager.resolve(bull, bear, debate_ctx)
            if persist:
                self._persist_debate(symbol, resolved)
            return resolved
        except Exception as exc:  # noqa: BLE001 - debate must never break the decision
            logger.warn(f"Research debate failed: {exc}")
            return None

    def _persist_debate(self, symbol, resolved):
        try:
            entry = {
                "symbol": symbol,
                "status": resolved.get("status"),
                "available": resolved.get("available"),
                "reason": resolved.get("reason"),
                "rating": resolved.get("rating"),
                "direction": resolved.get("direction"),
                "strength": resolved.get("strength"),
                "net": resolved.get("net"),
                "rationale": resolved.get("rationale"),
                "transcript": resolved.get("transcript") or [],
                "bull": resolved.get("bull") or {},
                "bear": resolved.get("bear") or {},
                "timestamp": int(time.time() * 1000),
            }
            db.collection("debate_history").insert({k: v for k, v in entry.items() if v is not None})
        except Exception as exc:  # noqa: BLE001
            logger.warn(f"Debate persist failed: {exc}")

    async def analyze(self, symbol="XAUUSD", context=None, persist=True):
        """Full decision cycle. Returns the decision dict (persisted + emitted).

        The ``news:processed`` trigger runs each cycle in its own thread with its
        own event loop, so an ``asyncio.Lock`` would be bound to whichever loop
        acquired it first and fail on every later loop ("bound to a different
        event loop"). A ``threading.Lock`` serializes cycles across threads;
        ``asyncio.to_thread`` waits for it without blocking the calling loop.
        """
        await asyncio.to_thread(self._lock.acquire)
        try:
            ctx = context or await self.build_context(symbol)
            results = await self.run_agents(ctx)

            risk_result = next((r for r in results if r.agent_id == "risk"), None)

            # Feature 1 — Bull vs Bear researcher debate, resolved into a rating.
            debate = await self._run_debate(symbol, ctx, results, persist=persist)

            consensus = compute_consensus(results, risk_result, debate_result=debate)
            news_result = next((r for r in results if r.agent_id == "news"), None)
            news_ids = (news_result.data.get("newsIds") if news_result else None) or []

            technical = next((r for r in results if r.agent_id == "technical"), None)
            tech_data = technical.data if technical else {}
            entry = tech_data.get("entry")
            stop_loss = tech_data.get("stopLoss")
            take_profit = tech_data.get("takeProfit")

            direction = consensus["direction"]
            decision = {
                "id": f"dec-{uuid.uuid4().hex[:12]}",
                "symbol": symbol,
                "direction": direction,
                "confidence": consensus["confidence"],
                "status": consensus["status"],
                "riskApproved": consensus["riskApproved"],
                "newsIds": news_ids,
                "weights": consensus["weights"],
                "agentScores": [r.to_dict() for r in results],
                "entry": float(entry) if entry is not None else None,
                "stopLoss": float(stop_loss) if stop_loss is not None else None,
                "takeProfit": float(take_profit) if take_profit is not None else None,
                "recommendation": {
                    "action": "hold" if consensus["status"] == "NO_TRADE" else "recommend",
                    "direction": direction,
                    "status": consensus["status"],
                },
                "xai": consensus["xai"],
                "debate": debate,
                "timestamp": int(time.time() * 1000),
            }

            if persist:
                try:
                    await decision_repository.insert(decision)
                except Exception as exc:  # noqa: BLE001
                    logger.warn(f"Decision persist failed: {exc}")

            # Publish AIDecisionMade to the event bus (distributed bus relays to Redis Streams).
            event_bus.emit("ai:decision", {"decision": decision})
            event_bus.emit("AIDecisionMade", {"decision": decision, "event": "AIDecisionMade"})
            try:
                distributed_event_bus.publish("AIDecisionMade", {"decision": decision})
            except Exception as exc:  # noqa: BLE001
                logger.warn(f"Distributed AIDecisionMade publish failed: {exc}")

            # Feed the auto-trade controller (90/70 gates) without changing its API.
            try:
                from ..execution.auto_controller import auto_trade_controller

                verdict, reasons = auto_trade_controller.evaluate(decision, context=ctx)
                decision["tradeVerdict"] = verdict
                decision["tradeReasons"] = reasons
            except Exception as exc:  # noqa: BLE001
                logger.warn(f"Auto-trade evaluation failed: {exc}")
                decision["tradeVerdict"] = "no-trade"

            return decision
        finally:
            self._lock.release()


decision_pipeline = DecisionPipeline()


class NewsDecisionWorker:
    """Single background worker for news-triggered AI decisions.

    The previous implementation spawned a new daemon thread for every
    ``news:processed`` event. Under a burst of events the backlog of 5-agent
    decision cycles serialized on the internal ``threading.Lock`` and starved
    the HTTP request path (observed as minutes-long hangs on
    ``/api/ai/analyze``). This worker consumes events from a small bounded
    queue on a single dedicated thread: while a decision is already running, a
    newer event replaces the pending one (latest-wins debounce), so exactly one
    worker thread exists regardless of event volume.
    """

    def __init__(self, max_pending=1):
        self._queue = queue.Queue(maxsize=max_pending)
        self._thread = None

    # ---- lifecycle -------------------------------------------------------- #
    def start(self):
        if self._thread is not None:
            return self
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="news-decision-worker"
        )
        self._thread.start()
        logger.info("News-decision worker started (single-threaded, bounded queue)")
        return self

    @property
    def worker_thread(self):
        return self._thread

    @property
    def pending(self):
        return self._queue.qsize()

    # ---- event ingestion -------------------------------------------------- #
    def enqueue(self, event=None):
        """Non-blocking enqueue with latest-wins coalescing while busy."""
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self._replace_latest(event)

    def _replace_latest(self, event):
        # Coalesce the single pending slot to the newest event. Called only
        # while the worker is busy, so a burst collapses to one pending item.
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            pass

    # ---- worker loop ------------------------------------------------------ #
    def _run_loop(self):
        while True:
            self._queue.get()
            try:
                asyncio.run(decision_pipeline.analyze(symbol="XAUUSD", context=None))
            except Exception as exc:  # noqa: BLE001 - the loop must never die
                logger.warn(f"News-triggered decision failed: {exc}")


news_decision_worker = NewsDecisionWorker()


def init_decision_pipeline():
    # Trigger an autonomous decision when processed news arrives. Events are
    # enqueued to a single background worker (bounded queue, latest-wins) so a
    # burst of news events never spawns one thread per event.
    def _on_news(event):
        news_decision_worker.enqueue(event)

    event_bus.on("news:processed", _on_news)
    news_decision_worker.start()
    logger.info("Decision pipeline initialized (news-triggered 5-agent analysis via single worker)")
    return decision_pipeline


async def analyze_symbol_pipeline(symbol="XAUUSD", context=None):
    return await decision_pipeline.analyze(symbol, context)
