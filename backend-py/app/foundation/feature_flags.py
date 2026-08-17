"""Feature flags mirroring the Node foundation featureFlags.js."""
from datetime import datetime, timezone

from .json_store import db
from .logger import logger

DEFAULT_FLAGS = {
    "ai.decisionCenter": True,
    "ai.autoTrade": False,
    "alerts.telegram": True,
    "alerts.whatsapp": False,
    "trading.autoExecute": False,
    "trading.dynamicReanalysis": True,
    "mt5.liveMode": False,
    "pwa.enabled": True,
    "news.aiAnalysis": True,
    "backtest.enabled": True,
    "monitoring.detailed": True,
    "cloud.enabled": True,
    "devops.ciEnabled": True,
    "production.readiness": True,
    "validation.autoRun": True,
}


class FeatureFlags:
    def __init__(self):
        self.col = db.collection("feature_flags")
        for key, value in DEFAULT_FLAGS.items():
            if not self.col.find_one({"key": key}):
                self.col.insert({"key": key, "value": value, "description": ""})

    def get(self, key, fallback=False):
        row = self.col.find_one({"key": key})
        return row["value"] if row else fallback

    def set(self, key, value, description=""):
        row = self.col.find_one({"key": key})
        if row:
            return self.col.update(row["id"], {"value": value, "description": description, "updatedAt": datetime.now(timezone.utc).isoformat()})
        return self.col.insert({"key": key, "value": value, "description": description})

    def all(self):
        return [{"key": r["key"], "value": r["value"], "description": r["description"]} for r in self.col.all()]


feature_flags = FeatureFlags()


def init_feature_flags():
    logger.info("Feature flags initialized")
    return feature_flags
