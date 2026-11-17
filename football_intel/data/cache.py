from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from typing import Any

from football_intel.config import data_dir


class Cache:
    """Small SQLite-backed JSON cache with TTL."""

    def __init__(self, ttl_hours: int = 6):
        self.ttl = ttl_hours * 3600
        self.path = os.path.join(data_dir(), "cache.sqlite3")
        self._init()

    def _init(self) -> None:
        with sqlite3.connect(self.path) as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, ts REAL)"
            )

    @staticmethod
    def _hash(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    def get(self, key: str, ttl: float | None = None) -> Any | None:
        with sqlite3.connect(self.path) as con:
            row = con.execute(
                "SELECT value, ts FROM cache WHERE key = ?", (self._hash(key),)
            ).fetchone()
        if not row:
            return None
        value, ts = row
        if time.time() - ts > (self.ttl if ttl is None else ttl):
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None

    def set(self, key: str, value: Any) -> None:
        with sqlite3.connect(self.path) as con:
            con.execute(
                "INSERT OR REPLACE INTO cache (key, value, ts) VALUES (?, ?, ?)",
                (self._hash(key), json.dumps(value, default=str), time.time()),
            )

    def clear(self) -> None:
        with sqlite3.connect(self.path) as con:
            con.execute("DELETE FROM cache")
