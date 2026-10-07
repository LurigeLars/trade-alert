from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import threading
from datetime import datetime
from typing import Literal

import pystray
from PIL import Image, ImageDraw

from .app import LOG_PATH, run_loop
from .config import Config, app_dir
from .news import CORE_TERM_LABELS, IMPACT_TERM_LABELS
from .notifier import notify
from .state import AlertRecord, StateStore

Health = Literal["ok", "waiting", "error", "paused"]


def make_status_icon(health: Health = "waiting", unread: int = 0) -> Image.Image:
    """Create the runtime tray icon; unread alerts add a persistent red badge."""
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    colors = {
        "ok": (52, 199, 89, 255),
        "waiting": (255, 159, 10, 255),
        "error": (255, 69, 58, 255),
        "paused": (142, 142, 147, 255),
    }
    accent = colors[health]

    draw.ellipse((5, 5, 59, 59), fill=(28, 28, 30, 255), outline=(210, 210, 215, 255), width=3)
    draw.line((18, 38, 28, 27, 36, 34, 47, 20), fill=accent, width=6)
    draw.ellipse((43, 16, 53, 26), fill=accent)

    if unread > 0:
        draw.ellipse((40, 0, 63, 23), fill=(255, 59, 48, 255), outline=(255, 255, 255, 255), width=2)
        draw.ellipse((49, 9, 54, 14), fill=(255, 255, 255, 255))

    return image


def monitoring_summary(config: Config) -> str:
    dtv = (
        f"AKTIV · watchlist {config.dtv_watchlist_id}"
        if config.dtv_watchlist_id
        else "INAKTIV · numeriskt watchlist-ID saknas"
    )
    symbols = ", ".join(config.official_symbols) or "inga"
    related = "ICEEUR:BRN1!, TVC:UKOIL"

    return (
        f"Profil\n{config.profile_name}\n\n"
        f"Källor\n"
        f"• Official TradingView News: AKTIV · {symbols}\n"
        f"• DTV News Flow: {dtv}\n\n"
        f"Polling\n"
        f"• huvudloop: var {config.poll_seconds} s\n"
        f"• Official TradingView: var {config.official_poll_seconds} s\n"
        f"• max {config.max_headlines} headlines per hämtning\n\n"
        f"Alerttröskel\n"
        f"• relevanspoäng ≥ {config.notification_min_score}\n"
        f"• +2 om rubriken innehåller core-termer:\n  {', '.join(CORE_TERM_LABELS)}\n"
        f"• +2 om rubriken innehåller impact-termer:\n  {', '.join(IMPACT_TERM_LABELS)}\n"
        f"• +2 om TradingView urgency = 1\n"
        f"• +2 om relaterad symbol är {related}\n\n"
        f"Första start\n"
        f"• äldre headlines än {config.startup_fresh_seconds} s baselinas utan alert\n\n"
        f"Modell\n"
        f"• ingen LLM används i hot path"
    )


def _local_timestamp(value: float | None) -> str:
    if value is None:
        return "okänd"
    try:
        return datetime.fromtimestamp(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return "okänd"


def format_alert_history(alerts: list[AlertRecord], unread_count: int) -> str:
    if not alerts:
        return "Inga riktiga Trade Alert-signaler har registrerats ännu."

    lines = [f"Olästa före öppning: {unread_count}", "", f"Senaste {len(alerts)} alerts:"]
    for alert in alerts:
        timestamp = _local_timestamp(alert.created_at)
        published = _local_timestamp(alert.published)
        marker = "OLÄST" if alert.unread else "läst"
        provider = alert.provider or alert.source
        lines.extend(
            [
                "",
                f"[{marker}] registrerad {timestamp} · {provider} · relevans {alert.score}",
                alert.headline,
                f"Publicerad: {published}",
                f"Källa: {alert.source}",
            ]
        )
        if alert.link:
            lines.append(f"Länk: {alert.link}")
    return "\n".join(lines)


def _show_native_text(title: str, text: str) -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x00000040)
    else:
        logging.info("%s\n%s", title, text)


class TrayController:
    def __init__(self, config: Config):
        self.config = config
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self._status = "Startar…"
        self._health: Health = "waiting"
        self._unread_count = self._load_unread_count()
        self.icon = pystray.Icon(
            "Trade Alert",
            icon=make_status_icon("waiting", self._unread_count),
            title=self._tooltip(),
            menu=pystray.Menu(
                pystray.MenuItem(lambda _item: self._status_line(), None, enabled=False),
                pystray.MenuItem(lambda _item: self._alerts_label(), self._show_alert_history),
                pystray.MenuItem("Vad bevakas?", self._show_monitoring),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    lambda _item: "Återuppta bevakning" if self.pause_event.is_set() else "Pausa bevakning",
                    self._toggle_pause,
                ),
                pystray.MenuItem("Testnotis", self._test_notification),
                pystray.MenuItem("Öppna loggmapp", self._open_logs),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Avsluta Trade Alert", self._exit),
            ),
        )
        self.worker = threading.Thread(
            target=self._worker_main,
            name="TradeAlertMonitor",
            daemon=True,
        )

    def run(self) -> None:
        self.worker.start()
        self.icon.run()

    def _load_unread_count(self) -> int:
        store = StateStore()
        try:
            return store.unread_alert_count()
        finally:
            store.close()

    def _status_line(self) -> str:
        return self._status

    def _alerts_label(self) -> str:
        if self._unread_count:
            return f"Senaste alerts ({self._unread_count} olästa)"
        return "Senaste alerts"

    def _tooltip(self) -> str:
        suffix = f" · {self._unread_count} olästa" if self._unread_count else ""
        return f"Trade Alert – {self._status}{suffix}"[:127]

    def _worker_main(self) -> None:
        store = StateStore()
        try:
            asyncio.run(
                run_loop(
                    self.config,
                    store,
                    stop_event=self.stop_event,
                    pause_event=self.pause_event,
                    status_callback=self._set_status,
                    alert_callback=self._on_alert,
                )
            )
        except Exception:
            logging.exception("Trade Alert monitoring thread failed")
            self._set_status("Fel – se logg", "error")
        finally:
            store.close()

    def _refresh_tray(self) -> None:
        try:
            self.icon.title = self._tooltip()
            self.icon.icon = make_status_icon(self._health, self._unread_count)
            self.icon.update_menu()
        except Exception:
            logging.debug("Tray icon was not ready for a refresh", exc_info=True)

    def _set_status(self, text: str, health: str = "ok") -> None:
        if health not in {"ok", "waiting", "error", "paused"}:
            health = "waiting"
        self._status = text
        self._health = health  # type: ignore[assignment]
        self._refresh_tray()

    def _on_alert(self, unread_count: int) -> None:
        self._unread_count = max(0, int(unread_count))
        self._refresh_tray()

    def _toggle_pause(self, _icon, _item) -> None:
        if self.pause_event.is_set():
            self.pause_event.clear()
            self._set_status("Återupptar…", "waiting")
        else:
            self.pause_event.set()
            self._set_status("Pausad", "paused")

    def _show_monitoring(self, _icon, _item) -> None:
        text = monitoring_summary(self.config)
        thread = threading.Thread(
            target=_show_native_text,
            args=("Trade Alert · Vad bevakas?", text),
            daemon=True,
        )
        thread.start()

    def _show_alert_history(self, _icon, _item) -> None:
        store = StateStore()
        try:
            unread_before = store.unread_alert_count()
            alerts = store.recent_alerts(limit=10)
            text = format_alert_history(alerts, unread_before)
            store.mark_alerts_read([alert.item_key for alert in alerts])
            self._unread_count = store.unread_alert_count()
        finally:
            store.close()

        self._refresh_tray()
        thread = threading.Thread(
            target=_show_native_text,
            args=("Trade Alert · Senaste alerts", text),
            daemon=True,
        )
        thread.start()

    def _test_notification(self, _icon, _item) -> None:
        previous_status = self._status
        previous_health = self._health
        if notify("Trade Alert", "Tray-appen fungerar."):
            self._set_status("Testnotis skickad", "ok")
        else:
            self._set_status("Notisfel · se logg", "error")
            return

        def restore() -> None:
            self._set_status(previous_status, previous_health)

        timer = threading.Timer(3.0, restore)
        timer.daemon = True
        timer.start()

    def _open_logs(self, _icon, _item) -> None:
        app_dir().mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(app_dir())  # type: ignore[attr-defined]
        else:
            logging.info("Logg: %s", LOG_PATH)

    def _exit(self, icon, _item) -> None:
        self.stop_event.set()
        icon.stop()


def run_tray(config: Config) -> None:
    TrayController(config).run()
