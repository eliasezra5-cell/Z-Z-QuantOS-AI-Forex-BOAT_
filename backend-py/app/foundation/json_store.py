"""JSON file store mirroring the Node foundation database.js (JsonCollection/JsonStore).

Each collection maps to `<DATA_DIR>/<name>.json`. Behavior (insert/update/upsert/
remove/find/findOne/all/count/clear/seed) matches the Node implementation 1:1.
"""
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .logger import logger


def _default_data_dir():
    from ..config import settings
    return settings.DATA_DIR


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _new_id():
    return str(uuid.uuid4())


class JsonCollection:
    def __init__(self, name, store):
        self.name = name
        self.store = store
        self.rows = []
        self._load()

    def _file(self):
        return self.store._file(self.name)

    def _load(self):
        f = self._file()
        if os.path.exists(f):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                self.rows = data if isinstance(data, list) else []
            except (json.JSONDecodeError, OSError):
                logger.warn(f"Failed to parse {self.name}, starting empty")
                self.rows = []

    def _persist(self):
        self.store._write(self.name, self.rows)

    def insert(self, doc):
        row = {"id": doc.get("id") or _new_id(), **doc, "createdAt": doc.get("createdAt") or _now_iso()}
        self.rows.append(row)
        self._persist()
        return row

    def insert_many(self, docs):
        rows = [
            {"id": d.get("id") or _new_id(), **d, "createdAt": d.get("createdAt") or _now_iso()}
            for d in docs
        ]
        self.rows.extend(rows)
        self._persist()
        return rows

    def update(self, doc_id, patch):
        for idx, row in enumerate(self.rows):
            if row.get("id") == doc_id:
                merged = {**row, **patch, "id": doc_id, "updatedAt": _now_iso()}
                self.rows[idx] = merged
                self._persist()
                return merged
        return None

    def upsert(self, doc):
        if doc.get("id") and any(r.get("id") == doc["id"] for r in self.rows):
            return self.update(doc["id"], doc)
        return self.insert(doc)

    def remove(self, doc_id):
        for idx, row in enumerate(self.rows):
            if row.get("id") == doc_id:
                removed = self.rows.pop(idx)
                self._persist()
                return removed
        return None

    def find(self, query=None, opts=None):
        query = query or {}
        opts = opts or {}
        res = [r for r in self.rows if all(r.get(k) == v for k, v in query.items())]
        if opts.get("sort"):
            sort_spec = opts["sort"]
            if isinstance(sort_spec, (list, tuple)):
                key, direction = sort_spec[0], sort_spec[1]
            else:
                key, direction = sort_spec, "desc"
            factor = -1 if direction == "desc" else 1

            def _sort_key(value):
                # Type-stable sort key: None first, then numbers, then strings.
                # Avoids '<' TypeError when a collection mixes field types.
                if value is None:
                    return (0, 0)
                if isinstance(value, bool):
                    return (1, int(value))
                if isinstance(value, (int, float)):
                    return (1, float(value))
                return (2, str(value))

            res = sorted(res, key=lambda r: _sort_key(r.get(key)), reverse=(factor == -1))
        if opts.get("limit"):
            res = res[: opts["limit"]]
        return res

    def find_one(self, query=None):
        query = query or {}
        for r in self.rows:
            if all(r.get(k) == v for k, v in query.items()):
                return r
        return None

    def all(self):
        return list(self.rows)

    def count(self):
        return len(self.rows)

    def clear(self):
        self.rows = []
        self._persist()


class JsonStore:
    def __init__(self, data_dir=None):
        self.dir = data_dir or os.environ.get("DATA_DIR") or _default_data_dir()
        os.makedirs(self.dir, exist_ok=True)
        self.log = logger
        self.collections = {}

    def _file(self, name):
        return os.path.join(self.dir, f"{name}.json")

    def _write(self, name, rows):
        os.makedirs(self.dir, exist_ok=True)
        target = self._file(name)
        fd, tmp = tempfile.mkstemp(dir=self.dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(rows, fh, indent=2, default=str)
            os.replace(tmp, target)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def collection(self, name):
        if name not in self.collections:
            self.collections[name] = JsonCollection(name, self)
        return self.collections[name]

    def seed(self, name, docs):
        col = self.collection(name)
        if col.count() == 0:
            col.insert_many(docs)


db = JsonStore()


def init_database():
    logger.info(f"Database initialized at {db.dir}")
    return db
