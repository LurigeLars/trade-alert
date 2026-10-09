from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from .config import app_dir


@dataclass(frozen=True, slots=True)
class AlertRecord:
    item_key: str
    created_at: float
    published: float | None
    source: str
    provider: str | None
    headline: str
    body: str
    score: int
    link: str | None
    unread: bool


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
            CREATE TABLE IF NOT EXISTS seen_items (
                dedupe_key TEXT PRIMARY KEY,
                first_seen REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alerts (
                item_key TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                published REAL,
                source TEXT NOT NULL,
                provider TEXT,
                headline TEXT NOT NULL,
                body TEXT NOT NULL,
                score INTEGER NOT NULL,
                link TEXT,
                unread INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_alerts_created_at
                ON alerts(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_alerts_unread
                ON alerts(unread, created_at DESC);
            """
        )
        self.con.execute(
            """
            INSERT OR IGNORE INTO seen_items(dedupe_key, first_seen)
            SELECT
                lower(trim(COALESCE(a.provider, ''))) || '|' ||
                    substr(s.item_key, length(a.source) + 2),
                s.first_seen
            FROM seen AS s
            JOIN alerts AS a ON a.item_key = s.item_key
            WHERE substr(s.item_key, 1, length(a.source) + 1) = a.source || ':'
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

    def seen_item(self, dedupe_key: str) -> bool:
        return self.con.execute(
            "SELECT 1 FROM seen_items WHERE dedupe_key=?",
            (dedupe_key,),
        ).fetchone() is not None

    def mark_seen_item(self, dedupe_key: str, at: float | None = None) -> None:
        self.con.execute(
            "INSERT OR IGNORE INTO seen_items(dedupe_key, first_seen) VALUES (?, ?)",
            (dedupe_key, at or time.time()),
        )
        self.con.commit()

    def record_alert(
        self,
        *,
        item_key: str,
        source: str,
        headline: str,
        body: str,
        score: int,
        provider: str | None = None,
        published: float | None = None,
        link: str | None = None,
        at: float | None = None,
    ) -> bool:
        cursor = self.con.execute(
            """
            INSERT OR IGNORE INTO alerts(
                item_key, created_at, published, source, provider,
                headline, body, score, link, unread
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                item_key,
                at or time.time(),
                published,
                source,
                provider,
                headline,
                body,
                int(score),
                link,
            ),
        )
        self.con.commit()
        return cursor.rowcount > 0

    def unread_alert_count(self) -> int:
        row = self.con.execute("SELECT COUNT(*) FROM alerts WHERE unread=1").fetchone()
        return int(row[0]) if row else 0

    def recent_alerts(self, limit: int = 10) -> list[AlertRecord]:
        rows = self.con.execute(
            """
            SELECT item_key, created_at, published, source, provider,
                   headline, body, score, link, unread
            FROM alerts
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [
            AlertRecord(
                item_key=row[0],
                created_at=float(row[1]),
                published=float(row[2]) if row[2] is not None else None,
                source=str(row[3]),
                provider=str(row[4]) if row[4] is not None else None,
                headline=str(row[5]),
                body=str(row[6]),
                score=int(row[7]),
                link=str(row[8]) if row[8] is not None else None,
                unread=bool(row[9]),
            )
            for row in rows
        ]

    def mark_alerts_read(self, item_keys: list[str]) -> None:
        keys = [str(key) for key in item_keys if str(key)]
        if not keys:
            return
        self.con.executemany(
            "UPDATE alerts SET unread=0 WHERE item_key=?",
            [(key,) for key in keys],
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

    def prune(self, days: int = 7, alert_days: int = 30) -> None:
        cutoff = time.time() - days * 86400
        alert_cutoff = time.time() - alert_days * 86400
        self.con.execute("DELETE FROM seen WHERE first_seen < ?", (cutoff,))
        self.con.execute("DELETE FROM seen_items WHERE first_seen < ?", (cutoff,))
        self.con.execute("DELETE FROM alerts WHERE created_at < ?", (alert_cutoff,))
        self.con.commit()
