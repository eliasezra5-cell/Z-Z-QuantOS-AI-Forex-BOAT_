"""Institutional 5-agent decision pipeline (strict 80/20 mandate).

Agents (run in parallel via ``asyncio.gather`` in the pipeline):

  - News Analysis Agent      weight 0.40  (directional)
  - Historical Pattern Agent weight 0.20  (directional)
  - Macro Analysis Agent     weight 0.20  (directional)
  - Technical Execution      weight 0.20  (EXECUTION ONLY, never direction)
  - Risk Manager Agent       VETO         (risk_approved=False -> NO_TRADE)

News Family weight = News + Historical + Macro = 80%; Technical = 20%.
Risk contributes no directional weight but has absolute veto power.
"""
from .base import AgentResult
from .news_agent import NewsAnalysisAgent
from .historical_agent import HistoricalPatternAgent
from .macro_agent import MacroAnalysisAgent
from .technical_agent import TechnicalExecutionAgent
from .risk_agent import RiskManagerAgent
from .custom_agent import CustomAgentRunner
from .bull_researcher_agent import BullResearcherAgent
from .bear_researcher_agent import BearResearcherAgent
from .sentiment_agent import SentimentAnalysisAgent
from .fundamentals_agent import FundamentalsAnalysisAgent
from .pro_institutional_agent import InstitutionalProAgent
from .kronos_forecast_agent import KronosForecastAgent

# Directional weights (100% total, technical = execution only)
NEWS_FAMILY = {"news": 0.40, "historical": 0.20, "macro": 0.20}
TECHNICAL_EXECUTION_WEIGHT = 0.20
CORE_AGENTS_80_20 = [
    {"id": "news", "name": "NewsAnalysisAgent", "weight": 0.40, "cls": NewsAnalysisAgent},
    {"id": "historical", "name": "HistoricalPatternAgent", "weight": 0.20, "cls": HistoricalPatternAgent},
    {"id": "macro", "name": "MacroAnalysisAgent", "weight": 0.20, "cls": MacroAnalysisAgent},
    {"id": "technical", "name": "TechnicalExecutionAgent", "weight": 0.20, "cls": TechnicalExecutionAgent},
]

__all__ = [
    "AgentResult",
    "NewsAnalysisAgent",
    "HistoricalPatternAgent",
    "MacroAnalysisAgent",
    "TechnicalExecutionAgent",
    "RiskManagerAgent",
    "CustomAgentRunner",
    "BullResearcherAgent",
    "BearResearcherAgent",
    "SentimentAnalysisAgent",
    "FundamentalsAnalysisAgent",
    "InstitutionalProAgent",
    "KronosForecastAgent",
    "NEWS_FAMILY",
    "TECHNICAL_EXECUTION_WEIGHT",
    "CORE_AGENTS_80_20",
]
