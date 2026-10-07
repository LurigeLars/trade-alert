from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Literal

import pystray
from PIL import Image, ImageDraw

from .app import LOG_PATH, run_loop
from .config import Config, app_dir
from .notifier import notify
from .state import StateStore

Health = Literal["ok", "waiting", "error", "paused"]


def make_status_icon(health: Health = "waiting") -> Image.Image:
    """Create the small runtime tray icon without shipping a binary asset."""
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
    return image


class TrayController:
    def __init__(self, config: Config):
        self.config = config
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self._status = "Startar…"
        self._health: Health = "waiting"
        self.icon = pystray.Icon(
            "Trade Alert",
            icon=make_status_icon("waiting"),
            title="Trade Alert – startar",
            menu=pystray.Menu(
                pystray.MenuItem(lambda _item: self._status, None, enabled=False),
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
                )
            )
        except Exception:
            logging.exception("Trade Alert monitoring thread failed")
            self._set_status("Fel – se logg", "error")
        finally:
            store.close()

    def _set_status(self, text: str, health: str = "ok") -> None:
        if health not in {"ok", "waiting", "error", "paused"}:
            health = "waiting"
        self._status = text
        self._health = health  # type: ignore[assignment]
        try:
            self.icon.title = f"Trade Alert – {text}"[:127]
            self.icon.icon = make_status_icon(self._health)
            self.icon.update_menu()
        except Exception:
            logging.debug("Tray icon was not ready for a status refresh", exc_info=True)

    def _toggle_pause(self, _icon, _item) -> None:
        if self.pause_event.is_set():
            self.pause_event.clear()
            self._set_status("Återupptar…", "waiting")
        else:
            self.pause_event.set()
            self._set_status("Pausad", "paused")

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
