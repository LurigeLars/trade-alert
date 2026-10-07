from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone

from .config import Config, app_dir
from .mcp_client import MCPToolError
from .news import Headline, fetch_dtv_news, fetch_official_news, relevance_score
from .notifier import notify
from .state import StateStore

LOG_PATH = app_dir() / "trade-alert.log"


def _setup_logging(verbose: bool = False) -> None:
    app_dir().mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )


def _notification(item: Headline, score: int) -> tuple[str, str]:
    provider = item.provider or item.source
    title = f"Trade Alert · {provider}"
    urgency = "TOP · " if item.urgency == 1 else ""
    body = f"{urgency}{item.title}\nPublicerad {item.published_label()} · relevans {score}"
    return title, body


async def _collect(config: Config, *, include_official: bool, dtv_since: str | None) -> tuple[list[Headline], bool, bool]:
    items: list[Headline] = []
    dtv_ok = False
    official_ok = False

    if config.dtv_watchlist_id:
        try:
            items.extend(
                await fetch_dtv_news(
                    url=config.dtv_url,
                    watchlist_id=config.dtv_watchlist_id,
                    since=dtv_since,
                    limit=config.max_headlines,
                )
            )
            dtv_ok = True
        except MCPToolError as exc:
            logging.warning("DTV news unavailable: %s", exc)

    if include_official:
        for symbol in config.official_symbols:
            try:
                items.extend(
                    await fetch_official_news(
                        url=config.trade_spine_url,
                        symbol=symbol,
                        limit=config.max_headlines,
                    )
                )
                official_ok = True
            except MCPToolError as exc:
                logging.warning("Official TradingView news unavailable for %s: %s", symbol, exc)

    deduped: dict[str, Headline] = {}
    for item in items:
        deduped[item.key] = item
    return list(deduped.values()), dtv_ok, official_ok


async def run_once(config: Config, store: StateStore, *, include_official: bool = True) -> dict:
    first_cycle = not store.initialized()
    dtv_since = store.get_meta("dtv_last_success")
    items, dtv_ok, official_ok = await _collect(
        config, include_official=include_official, dtv_since=dtv_since
    )
    now = time.time()
    notified = 0
    fresh = 0

    for item in sorted(items, key=lambda x: x.published or 0):
        if store.seen(item.key):
            continue
        fresh += 1
        score = relevance_score(item)
        age = item.age_seconds
        baseline_old = first_cycle and (age is None or age > config.startup_fresh_seconds)
        if score >= config.notification_min_score and not baseline_old:
            title, body = _notification(item, score)
            notify(title, body)
            notified += 1
        store.mark_seen(item.key, at=now)

    if dtv_ok:
        store.set_meta("dtv_last_success", datetime.now(timezone.utc).isoformat())
    if first_cycle:
        store.mark_initialized()
    store.prune()

    if include_official:
        if not config.dtv_watchlist_id and not official_ok:
            logging.error("No usable news source: DTV watchlist is unset and Official TradingView failed")
        elif config.dtv_watchlist_id and not (dtv_ok or official_ok):
            logging.error("All configured news sources failed")
    elif config.dtv_watchlist_id and not dtv_ok:
        logging.warning("DTV news source failed on a DTV-only cycle")

    return {
        "fresh": fresh,
        "notified": notified,
        "dtv_ok": dtv_ok,
        "official_ok": official_ok,
    }


async def _sleep_interruptible(seconds: float, stop_event=None) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if stop_event is not None and stop_event.is_set():
            return
        await asyncio.sleep(min(0.5, max(0.0, deadline - time.monotonic())))


async def run_loop(
    config: Config,
    store: StateStore,
    *,
    stop_event=None,
    pause_event=None,
    status_callback=None,
) -> None:
    next_official = 0.0
    last_official_ok = False

    while stop_event is None or not stop_event.is_set():
        if pause_event is not None and pause_event.is_set():
            if status_callback is not None:
                status_callback("Pausad", "paused")
            await _sleep_interruptible(0.5, stop_event)
            continue

        now = time.monotonic()
        include_official = now >= next_official
        try:
            result = await run_once(config, store, include_official=include_official)
            if include_official:
                last_official_ok = result["official_ok"]
            logging.info(
                "cycle fresh=%s notified=%s dtv=%s official=%s",
                result["fresh"],
                result["notified"],
                result["dtv_ok"],
                result["official_ok"],
            )

            if status_callback is not None:
                if result["dtv_ok"] and last_official_ok:
                    status_callback("Aktiv · DTV + Official TV", "ok")
                elif result["dtv_ok"]:
                    status_callback("Aktiv · DTV", "ok")
                elif last_official_ok:
                    status_callback("Aktiv · Official TV", "ok")
                elif include_official:
                    status_callback("Källfel · se logg", "error")
                else:
                    status_callback("Väntar på nästa källpoll", "waiting")
        except Exception:
            logging.exception("trade-alert cycle failed")
            if status_callback is not None:
                status_callback("Fel · se logg", "error")

        if include_official:
            next_official = time.monotonic() + config.official_poll_seconds
        await _sleep_interruptible(config.poll_seconds, stop_event)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local low-latency trade news notifier")
    parser.add_argument("--once", action="store_true", help="Run one acquisition cycle and exit")
    parser.add_argument("--test-notification", action="store_true", help="Show a Windows test notification and exit")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--no-tray", action="store_true", help="Run the monitor in the foreground without a tray icon")
    args = parser.parse_args()

    _setup_logging(args.verbose)
    config = Config.load()
    if args.test_notification:
        notify("Trade Alert", "Testnotis fungerar.")
        return

    store = StateStore()
    try:
        if args.once:
            result = asyncio.run(run_once(config, store))
            print(result)
            return
    finally:
        store.close()

    if os.name == "nt" and not args.no_tray:
        from .tray import run_tray
        run_tray(config)
    else:
        foreground_store = StateStore()
        try:
            asyncio.run(run_loop(config, foreground_store))
        finally:
            foreground_store.close()


if __name__ == "__main__":
    main()
