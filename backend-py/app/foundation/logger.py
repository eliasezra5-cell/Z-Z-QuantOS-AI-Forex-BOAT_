"""Structured JSON logger mirroring the Node foundation logger."""
import json
import os
import sys
from datetime import datetime, timezone

LEVELS = {"debug": 10, "info": 20, "warn": 30, "error": 40, "fatal": 50}
REDACT_KEYS = {"password", "secret", "token", "apiKey", "api_key", "authorization"}


def _redact(meta: dict):
    for k, v in list(meta.items()):
        if k in REDACT_KEYS:
            meta[k] = "[REDACTED]"
        elif isinstance(v, dict):
            meta[k] = _redact(v)
    return meta


class Logger:
    def __init__(self, name="quantos", level=None):
        self.name = name
        self.level = LEVELS.get(level or os.environ.get("LOG_LEVEL", "info"), 20)

    def child(self, bindings=None):
        mod = (bindings or {}).get("module", "sub")
        return Logger(f"{self.name}.{mod}")

    def _write(self, lvl, msg, meta):
        if LEVELS[lvl] < self.level:
            return
        line = {"ts": datetime.now(timezone.utc).isoformat(), "level": lvl, "service": self.name, "msg": msg}
        if meta and isinstance(meta, dict) and meta:
            line["meta"] = _redact(dict(meta))
        out = json.dumps(line, default=str)
        if lvl in ("error", "fatal"):
            sys.stderr.write(out + "\n")
        else:
            sys.stdout.write(out + "\n")

    def debug(self, msg, meta=None):
        self._write("debug", msg, meta)

    def info(self, msg, meta=None):
        self._write("info", msg, meta)

    def warn(self, msg, meta=None):
        self._write("warn", msg, meta)

    def error(self, msg, meta=None):
        self._write("error", msg, meta)

    def fatal(self, msg, meta=None):
        self._write("fatal", msg, meta)


logger = Logger()


def create_child_logger(name):
    return Logger(name)
