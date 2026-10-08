from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_OFFICIAL_SYMBOLS = ("ICEEUR:BRN1!", "NYMEX:RB1!")


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
    official_symbols: tuple[str, ...] = DEFAULT_OFFICIAL_SYMBOLS
    poll_seconds: int = 20
    official_poll_seconds: int = 30
    dtv_max_headlines: int = 200
    official_max_headlines: int = 25
    notification_min_score: int = 2
    startup_fresh_seconds: int = 120
    # Local-only ingress; no upstream connector or Truth Social scraper is bundled.
    breaking_inbox_enabled: bool = True
    breaking_poll_seconds: float = 1.0
    breaking_max_age_seconds: int = 300
    breaking_authorized_sources: tuple[str, ...] = ()
    # Public third-party archive explicitly offers a subscription RSS endpoint.
    truth_rss_enabled: bool = True
    truth_rss_poll_seconds: int = 30
    truth_rss_max_age_seconds: int = 900
    # Anonymous public-account endpoint; refuses any login wall or denial.
    truth_direct_enabled: bool = True
    truth_direct_poll_seconds: int = 15
    truth_direct_max_age_seconds: int = 300

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or app_dir() / "config.json"
        if not path.exists():
            config = cls()
            config.save(path)
            return config
        raw = json.loads(path.read_text(encoding="utf-8"))
        migrated = False
        legacy_max = raw.pop("max_headlines", None)
        if legacy_max is not None:
            migrated = True
        if "dtv_max_headlines" not in raw:
            raw["dtv_max_headlines"] = 200
            migrated = True
        if "official_max_headlines" not in raw:
            raw["official_max_headlines"] = min(int(legacy_max or 25), 100)
            migrated = True
        if "official_symbols" in raw:
            symbols = tuple(raw["official_symbols"])
            if raw.get("profile_name") == "Oil / Brent" and symbols == ("ICEEUR:BRN1!",):
                symbols = DEFAULT_OFFICIAL_SYMBOLS
                migrated = True
            raw["official_symbols"] = symbols
        if "breaking_authorized_sources" in raw:
            raw["breaking_authorized_sources"] = tuple(raw["breaking_authorized_sources"])
        config = cls(**raw)
        config.validate()
        if migrated:
            config.save(path)
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
        if not 1 <= int(self.dtv_max_headlines) <= 200:
            raise ValueError("dtv_max_headlines must be between 1 and 200")
        if not 1 <= int(self.official_max_headlines) <= 100:
            raise ValueError("official_max_headlines must be between 1 and 100")
        if not 0 <= int(self.notification_min_score) <= 10:
            raise ValueError("notification_min_score must be between 0 and 10")
        if not 0 <= int(self.startup_fresh_seconds) <= 3600:
            raise ValueError("startup_fresh_seconds must be between 0 and 3600")
        if not isinstance(self.breaking_inbox_enabled, bool):
            raise ValueError("breaking_inbox_enabled must be a boolean")
        if not 0.2 <= float(self.breaking_poll_seconds) <= 60:
            raise ValueError("breaking_poll_seconds must be between 0.2 and 60")
        if not 10 <= int(self.breaking_max_age_seconds) <= 3600:
            raise ValueError("breaking_max_age_seconds must be between 10 and 3600")
        if len(self.breaking_authorized_sources) != len(set(self.breaking_authorized_sources)):
            raise ValueError("duplicate breaking source identifiers")
        for name in self.breaking_authorized_sources:
            if not isinstance(name, str) or not name.isupper() or len(name) > 80:
                raise ValueError("invalid breaking source identifier")
        if not isinstance(self.truth_rss_enabled, bool):
            raise ValueError("truth_rss_enabled must be boolean")
        if not 20 <= int(self.truth_rss_poll_seconds) <= 3600:
            raise ValueError("truth_rss_poll_seconds must be 20-3600")
        if not 60 <= int(self.truth_rss_max_age_seconds) <= 3600:
            raise ValueError("truth_rss_max_age_seconds must be 60-3600")
        if not isinstance(self.truth_direct_enabled, bool):
            raise ValueError("truth_direct_enabled must be boolean")
        if not 10 <= int(self.truth_direct_poll_seconds) <= 3600:
            raise ValueError("truth_direct_poll_seconds must be 10-3600")
        if not 30 <= int(self.truth_direct_max_age_seconds) <= 3600:
            raise ValueError("truth_direct_max_age_seconds must be 30-3600")
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
        payload["breaking_authorized_sources"] = list(self.breaking_authorized_sources)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path
