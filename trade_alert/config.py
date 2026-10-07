from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


def app_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "TradeAlert"


@dataclass(slots=True)
class Config:
    profile_name: str = "Oil / Brent"
    theme_mode: str = "system"
    dtv_url: str = "http://127.0.0.1:8765/mcp"
    trade_spine_url: str = "http://127.0.0.1:8773/mcp"
    dtv_watchlist_id: str | None = None
    official_symbols: tuple[str, ...] = ("ICEEUR:BRN1!",)
    poll_seconds: int = 20
    official_poll_seconds: int = 30
    max_headlines: int = 25
    notification_min_score: int = 2
    startup_fresh_seconds: int = 120

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or app_dir() / "config.json"
        if not path.exists():
            config = cls()
            config.save(path)
            return config
        raw = json.loads(path.read_text(encoding="utf-8"))
        if "official_symbols" in raw:
            raw["official_symbols"] = tuple(raw["official_symbols"])
        config = cls(**raw)
        config.validate()
        return config

    def validate(self) -> None:
        if not self.profile_name or len(self.profile_name) > 160:
            raise ValueError("profile_name must be between 1 and 160 characters")
        if self.theme_mode not in {"system", "light", "dark"}:
            raise ValueError("theme_mode must be system, light or dark")
        if not 5 <= int(self.poll_seconds) <= 3600:
            raise ValueError("poll_seconds must be between 5 and 3600")
        if not 5 <= int(self.official_poll_seconds) <= 3600:
            raise ValueError("official_poll_seconds must be between 5 and 3600")
        if not 1 <= int(self.max_headlines) <= 100:
            raise ValueError("max_headlines must be between 1 and 100")
        if not 0 <= int(self.notification_min_score) <= 10:
            raise ValueError("notification_min_score must be between 0 and 10")
        if not 0 <= int(self.startup_fresh_seconds) <= 3600:
            raise ValueError("startup_fresh_seconds must be between 0 and 3600")
        if self.dtv_watchlist_id is not None and not str(self.dtv_watchlist_id).isdigit():
            raise ValueError("dtv_watchlist_id must be numeric when set")
        for symbol in self.official_symbols:
            if not symbol or len(symbol) > 128:
                raise ValueError("official_symbols contains an invalid symbol")

    def save(self, path: Path | None = None) -> Path:
        self.validate()
        path = path or app_dir() / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload["official_symbols"] = list(self.official_symbols)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path
