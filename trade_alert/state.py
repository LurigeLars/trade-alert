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
    dtv_first_seen: float | None
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
            CREATE TABLE IF NOT EXISTS source_observations (
                dedupe_key TEXT NOT NULL,
                source TEXT NOT NULL,
                first_seen REAL NOT NULL,
                PRIMARY KEY(dedupe_key, source)
            );
            CREATE INDEX IF NOT EXISTS idx_source_observations_source_seen
                ON source_observations(source, first_seen DESC);
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alerts (
                item_key TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                published REAL,
                dedupe_key TEXT,
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
        alert_columns = {
            str(row[1]) for row in self.con.execute("PRAGMA table_info(alerts)").fetchall()
        }
        if "dedupe_key" not in alert_columns:
            self.con.execute("ALTER TABLE alerts ADD COLUMN dedupe_key TEXT")

        self.con.execute(
            """
            UPDATE alerts
            SET dedupe_key =
                lower(trim(COALESCE(provider, ''))) || '|' ||
                substr(item_key, length(source) + 2)
            WHERE dedupe_key IS NULL
               OR dedupe_key = ''
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

    def mark_source_observations(
        self,
        observations: list[tuple[str, str]],
        *,
        at: float | None = None,
    ) -> None:
        if not observations:
            return
        first_seen = at or time.time()
        unique = list(dict.fromkeys(
            (str(dedupe_key), str(source))
            for dedupe_key, source in observations
            if str(dedupe_key) and str(source)
        ))
        if not unique:
            return
        self.con.executemany(
            """
            INSERT OR IGNORE INTO source_observations(dedupe_key, source, first_seen)
            VALUES (?, ?, ?)
            """,
            [(dedupe_key, source, first_seen) for dedupe_key, source in unique],
        )
        self.con.commit()

    def source_first_seen(self, dedupe_key: str, source: str) -> float | None:
        row = self.con.execute(
            """
            SELECT first_seen
            FROM source_observations
            WHERE dedupe_key=? AND source=?
            """,
            (dedupe_key, source),
        ).fetchone()
        return float(row[0]) if row else None

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
        dedupe_key: str | None = None,
        link: str | None = None,
        at: float | None = None,
    ) -> bool:
        cursor = self.con.execute(
            """
            INSERT OR IGNORE INTO alerts(
                item_key, created_at, published, dedupe_key, source, provider,
                headline, body, score, link, unread
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                item_key,
                at or time.time(),
                published,
                dedupe_key,
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
            SELECT
                a.item_key,
                a.created_at,
                a.published,
                d.first_seen AS dtv_first_seen,
                a.source,
                a.provider,
                a.headline,
                a.body,
                a.score,
                a.link,
                a.unread
            FROM alerts AS a
            LEFT JOIN source_observations AS d
              ON d.dedupe_key = a.dedupe_key
             AND d.source = 'DTV_NEWS_FLOW'
            ORDER BY a.created_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [
            AlertRecord(
                item_key=row[0],
                created_at=float(row[1]),
                published=float(row[2]) if row[2] is not None else None,
                dtv_first_seen=float(row[3]) if row[3] is not None else None,
                source=str(row[4]),
                provider=str(row[5]) if row[5] is not None else None,
                headline=str(row[6]),
                body=str(row[7]),
                score=int(row[8]),
                link=str(row[9]) if row[9] is not None else None,
                unread=bool(row[10]),
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
        self.con.execute(
            "DELETE FROM source_observations WHERE first_seen < ?",
            (alert_cutoff,),
        )
        self.con.execute("DELETE FROM alerts WHERE created_at < ?", (alert_cutoff,))
        self.con.commit()
