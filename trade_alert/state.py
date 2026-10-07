from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .config import app_dir


class StateStore:
    def __init__(self, path: Path | None = None):
        self.path = path or app_dir() / "state.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(
            """
            CREATE TABLE IF NOT EXISTS seen (
                item_key TEXT PRIMARY KEY,
                first_seen REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self.con.commit()

    def close(self) -> None:
        self.con.close()

    def seen(self, key: str) -> bool:
        return self.con.execute("SELECT 1 FROM seen WHERE item_key=?", (key,)).fetchone() is not None

    def mark_seen(self, key: str, at: float | None = None) -> None:
        self.con.execute(
            "INSERT OR IGNORE INTO seen(item_key, first_seen) VALUES (?, ?)",
            (key, at or time.time()),
        )
        self.con.commit()

    def get_meta(self, key: str) -> str | None:
        row = self.con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.con.execute(
            "INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.con.commit()

    def initialized(self) -> bool:
        return self.get_meta("initialized_at") is not None

    def mark_initialized(self) -> None:
        self.set_meta("initialized_at", str(time.time()))

    def prune(self, days: int = 7) -> None:
        cutoff = time.time() - days * 86400
        self.con.execute("DELETE FROM seen WHERE first_seen < ?", (cutoff,))
        self.con.commit()
