from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path


DEFAULT_OFFICIAL_SYMBOLS = ()  # Official TradingView retired by user request.
MAX_WATCHES = 50
MAX_WATCH_TERMS = 50


@dataclass(frozen=True, slots=True)
class Watch:
    """User-defined News Flow watch: alert when a headline matches a keyword or symbol."""

    name: str
    keywords: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    enabled: bool = True

    @classmethod
    def from_dict(cls, raw: dict) -> "Watch":
        if not isinstance(raw, dict):
            raise ValueError("each watch must be an object")
        unknown = set(raw) - {"name", "keywords", "symbols", "enabled"}
        if unknown:
            raise ValueError(f"unknown watch fields: {', '.join(sorted(unknown))}")
        return cls(
            name=raw.get("name", ""),
            keywords=tuple(raw.get("keywords") or ()),
            symbols=tuple(raw.get("symbols") or ()),
            enabled=raw.get("enabled", True),
        )

    def validate(self) -> None:
        if not isinstance(self.name, str) or not 1 <= len(self.name.strip()) <= 80:
            raise ValueError("watch name must be 1-80 characters")
        if not isinstance(self.enabled, bool):
            raise ValueError(f"watch {self.name}: enabled must be boolean")
        if not self.keywords and not self.symbols:
            raise ValueError(f"watch {self.name}: needs at least one keyword or symbol")
        if len(self.keywords) > MAX_WATCH_TERMS or len(self.symbols) > MAX_WATCH_TERMS:
            raise ValueError(f"watch {self.name}: at most {MAX_WATCH_TERMS} keywords and symbols")
        for word in self.keywords:
            if not isinstance(word, str) or not 1 <= len(word.strip()) <= 80:
                raise ValueError(f"watch {self.name}: keywords must be 1-80 characters")
        for symbol in self.symbols:
            if (not isinstance(symbol, str) or ":" not in symbol or len(symbol) > 128
                    or any(c.isspace() for c in symbol)):
                raise ValueError(f"watch {self.name}: symbols must be exact EXCHANGE:SYMBOL")


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
    dtv_replay_overlap_seconds: int = 3600
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
    # Optional local Chrome extension. Does not manage browser sessions.
    chrome_bridge_enabled: bool = False
    chrome_bridge_poll_seconds: float = 1.0
    chrome_bridge_max_age_seconds: int = 300
    # Disabled until a verified, locally authorized real-time price producer exists.
    market_correlation_enabled: bool = False
    market_correlation_brent_symbol: str = "NYMEX:BZZ2026"
    market_correlation_nasdaq_symbol: str = "CME_MINI:NQ1!"
    market_correlation_authorized_sources: tuple[str, ...] = ("DTV_RESIDENT",)
    market_correlation_max_age_seconds: int = 180
    market_correlation_poll_seconds: float = 10.0
    market_correlation_auto_enable_resident: bool = True
    # The built-in oil relevance rules; user watches below are matched in addition.
    oil_watch_enabled: bool = True
    watches: tuple[Watch, ...] = ()

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
        if "dtv_replay_overlap_seconds" not in raw:
            raw["dtv_replay_overlap_seconds"] = 3600
            migrated = True
        if "official_symbols" in raw:
            symbols = tuple(raw["official_symbols"])
            if raw.get("profile_name") == "Oil / Brent" and symbols == ("ICEEUR:BRN1!",):
                symbols = DEFAULT_OFFICIAL_SYMBOLS
                migrated = True
            raw["official_symbols"] = symbols
        if "breaking_authorized_sources" in raw:
            raw["breaking_authorized_sources"] = tuple(raw["breaking_authorized_sources"])
        if "market_correlation_authorized_sources" in raw:
            raw["market_correlation_authorized_sources"] = tuple(raw["market_correlation_authorized_sources"])
        if "watches" in raw:
            if not isinstance(raw["watches"], list):
                raise ValueError("watches must be a list")
            raw["watches"] = tuple(Watch.from_dict(item) for item in raw["watches"])
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
        if not 0 <= int(self.dtv_replay_overlap_seconds) <= 7200:
            raise ValueError("dtv_replay_overlap_seconds must be between 0 and 7200")
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
        if not isinstance(self.chrome_bridge_enabled, bool):
            raise ValueError("chrome_bridge_enabled must be boolean")
        if not 0.2 <= float(self.chrome_bridge_poll_seconds) <= 30:
            raise ValueError("chrome_bridge_poll_seconds must be 0.2-30")
        if not 30 <= int(self.chrome_bridge_max_age_seconds) <= 1800:
            raise ValueError("chrome_bridge_max_age_seconds must be 30-1800")
        if not 5.0 <= float(self.market_correlation_poll_seconds) <= 60.0:
            raise ValueError("market_correlation_poll_seconds must be 5-60")
        if not isinstance(self.market_correlation_auto_enable_resident, bool):
            raise ValueError("market_correlation_auto_enable_resident must be boolean")
        if not isinstance(self.market_correlation_enabled, bool):
            raise ValueError("market_correlation_enabled must be boolean")
        if not 60 <= int(self.market_correlation_max_age_seconds) <= 900:
            raise ValueError("market_correlation_max_age_seconds must be 60-900")
        for symbol in (self.market_correlation_brent_symbol, self.market_correlation_nasdaq_symbol):
            if not isinstance(symbol, str) or ":" not in symbol or len(symbol) > 128:
                raise ValueError("market correlation references must be exact exchange:symbol pairs")
        if len(self.market_correlation_authorized_sources) != len(set(self.market_correlation_authorized_sources)):
            raise ValueError("duplicate market-correlation sources")
        for name in self.market_correlation_authorized_sources:
            if not isinstance(name, str) or not name.isupper() or len(name) > 80:
                raise ValueError("invalid market-correlation source")
        if self.dtv_watchlist_id is not None and not str(self.dtv_watchlist_id).isdigit():
            raise ValueError("dtv_watchlist_id must be numeric when set")
        for symbol in self.official_symbols:
            if not symbol or len(symbol) > 128:
                raise ValueError("official_symbols contains an invalid symbol")
        if not isinstance(self.oil_watch_enabled, bool):
            raise ValueError("oil_watch_enabled must be boolean")
        if len(self.watches) > MAX_WATCHES:
            raise ValueError(f"at most {MAX_WATCHES} watches")
        names = [watch.name.strip().casefold() for watch in self.watches]
        if len(names) != len(set(names)):
            raise ValueError("watch names must be unique")
        for watch in self.watches:
            watch.validate()

    def update_from(self, other: "Config") -> None:
        """Apply a freshly loaded config to this shared instance, so running workers see it."""
        for field in fields(self):
            setattr(self, field.name, getattr(other, field.name))

    def save(self, path: Path | None = None) -> Path:
        self.validate()
        path = path or app_dir() / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload["official_symbols"] = list(self.official_symbols)
        payload["breaking_authorized_sources"] = list(self.breaking_authorized_sources)
        payload["market_correlation_authorized_sources"] = list(self.market_correlation_authorized_sources)
        # Write then rename, so a reader never sees a half-written file.
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        return path


class ConfigReloader:
    """Re-reads config.json when it changes on disk (settings window or a remote edit)."""

    def __init__(self, config: Config, path: Path | None = None):
        self.config = config
        self.path = path or app_dir() / "config.json"
        self._mtime = self._stat()

    def _stat(self) -> float | None:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return None

    def poll(self) -> bool:
        mtime = self._stat()
        if mtime is None or mtime == self._mtime:
            return False
        self._mtime = mtime
        try:
            fresh = Config.load(self.path)
        except (OSError, ValueError, TypeError) as exc:
            # Keep running on the last valid settings; the log says why the edit was refused.
            logging.error("config.json change ignored, keeping previous settings: %s", exc)
            return False
        self.config.update_from(fresh)
        self._mtime = self._stat()
        logging.info("config.json reloaded")
        return True
