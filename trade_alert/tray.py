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
from .news import CORE_TERM_LABELS, IMPACT_TERM_LABELS, OIL_ROUTING_SYMBOLS
from .notifier import notify
from .state import AlertRecord, StateStore
from .windows_ui import (
    allow_windows_dark_mode_for_window,
    configure_windows_native_menu_theme,
    flush_windows_menu_themes,
)

Health = Literal["ok", "waiting", "error", "paused"]
Theme = Literal["light", "dark"]

_THEME_LABELS = {
    "system": "Följ Windows",
    "light": "Ljust",
    "dark": "Mörkt",
}


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


def monitoring_summary(
    config: Config,
    *,
    resolved_watchlist_name: str | None = None,
    auto_pinned_watchlist: bool = False,
) -> str:
    symbols = ", ".join(config.official_symbols) or "inga"
    routing = ", ".join(sorted(OIL_ROUTING_SYMBOLS))

    if config.dtv_watchlist_id:
        dtv_context = "pinnad lokal TradingView-watchlist"
    elif auto_pinned_watchlist:
        name = resolved_watchlist_name or "namn okänt"
        dtv_context = f"auto-pinnad lokalt från aktiv TradingView-lista · {name}"
    else:
        dtv_context = (
            "auto-upptäcker aktiv TradingView-watchlist vid första körning; "
            "minst ett verifierat oljeankare krävs"
        )

    return (
        f"Profil\n{config.profile_name}\n\n"
        f"Källor\n"
        f"• DTV TradingView News Flow: PRIMÄR · broad discovery\n"
        f"  {dtv_context}\n"
        f"• Official TradingView symbol-news: SEKUNDÄR · targeted corroboration\n"
        f"  {symbols}\n\n"
        f"Polling\n"
        f"• News Flow: var {config.poll_seconds} s · max {config.dtv_max_headlines} headlines\n"
        f"• Official TradingView: var {config.official_poll_seconds} s · "
        f"max {config.official_max_headlines} headlines/symbol\n\n"
        f"Alertfilter\n"
        f"• relevanspoäng ≥ {config.notification_min_score}\n"
        f"• +2 för explicit olje/core-term i rubriken:\n  {', '.join(CORE_TERM_LABELS)}\n"
        f"• +2 för impact-term ENDAST när oljecontext finns:\n  {', '.join(IMPACT_TERM_LABELS)}\n"
        f"• +1 för olje-relaterad provider-symbol (routing evidence, räcker aldrig ensam)\n"
        f"• +1 för TradingView urgency = 1, endast när oljecontext finns\n"
        f"• routing-symboler: {routing}\n\n"
        f"Första News Flow-start\n"
        f"• äldre headlines än {config.startup_fresh_seconds} s baselinas utan alert\n"
        f"• watchlist-ID sparas endast lokalt i Trade Alert-state; inget konto-ID committas\n\n"
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


def windows_apps_use_dark_mode() -> bool:
    """Return the current Windows app-theme preference; fail safely to light."""
    if os.name != "nt":
        return False

    try:
        import winreg

        path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return int(value) == 0
    except (OSError, ValueError, TypeError):
        return False


def resolve_theme(theme_mode: str, *, system_dark: bool | None = None) -> Theme:
    if theme_mode == "dark":
        return "dark"
    if theme_mode == "light":
        return "light"
    if system_dark is None:
        system_dark = windows_apps_use_dark_mode()
    return "dark" if system_dark else "light"


def theme_palette(theme: Theme) -> dict[str, str]:
    if theme == "dark":
        return {
            "window": "#202020",
            "surface": "#1e1e1e",
            "text": "#f3f3f3",
            "muted": "#b9b9b9",
            "border": "#3f3f46",
            "button": "#2d2d30",
            "button_active": "#3a3a3d",
            "selection": "#264f78",
            "selection_text": "#ffffff",
        }
    return {
        "window": "#f6f6f6",
        "surface": "#ffffff",
        "text": "#202020",
        "muted": "#5f5f5f",
        "border": "#d0d0d0",
        "button": "#e9e9e9",
        "button_active": "#dcdcdc",
        "selection": "#0078d4",
        "selection_text": "#ffffff",
    }


def _apply_windows_titlebar_theme(root, *, dark: bool) -> None:
    if os.name != "nt":
        return
    try:
        root.update_idletasks()
        hwnd = root.winfo_id()
        value = ctypes.c_int(1 if dark else 0)
        dwm = ctypes.windll.dwmapi
        for attribute in (20, 19):
            result = dwm.DwmSetWindowAttribute(
                hwnd,
                attribute,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            if result == 0:
                break
    except Exception:
        logging.debug("Could not apply Windows title-bar theme", exc_info=True)


def _show_text_window(title: str, text: str, theme_mode: str) -> None:
    """Open a selectable, copyable information window using the effective theme."""
    if os.name != "nt":
        logging.info("%s\n%s", title, text)
        return

    def run_window() -> None:
        import tkinter as tk

        theme = resolve_theme(theme_mode)
        palette = theme_palette(theme)

        root = tk.Tk()
        root.title(title)
        root.geometry("860x680")
        root.minsize(620, 420)
        root.configure(bg=palette["window"])
        _apply_windows_titlebar_theme(root, dark=theme == "dark")

        outer = tk.Frame(root, bg=palette["window"], padx=14, pady=14)
        outer.pack(fill="both", expand=True)

        text_frame = tk.Frame(
            outer,
            bg=palette["surface"],
            highlightbackground=palette["border"],
            highlightthickness=1,
        )
        text_frame.pack(fill="both", expand=True)

        scrollbar = tk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")

        text_widget = tk.Text(
            text_frame,
            wrap="word",
            yscrollcommand=scrollbar.set,
            bg=palette["surface"],
            fg=palette["text"],
            insertbackground=palette["text"],
            selectbackground=palette["selection"],
            selectforeground=palette["selection_text"],
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=16,
            pady=14,
            font=("Segoe UI", 10),
            spacing1=1,
            spacing3=2,
        )
        text_widget.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=text_widget.yview)

        text_widget.insert("1.0", text)

        headings = {"Profil", "Källor", "Polling", "Alertfilter", "Första News Flow-start", "Modell"}
        text_widget.tag_configure("heading", font=("Segoe UI Semibold", 10))
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.strip() in headings:
                text_widget.tag_add("heading", f"{line_number}.0", f"{line_number}.end")

        text_widget.configure(state="disabled")

        button_bar = tk.Frame(outer, bg=palette["window"], pady=10)
        button_bar.pack(fill="x")

        def select_all(_event=None):
            text_widget.tag_add("sel", "1.0", "end-1c")
            text_widget.mark_set("insert", "1.0")
            text_widget.see("1.0")
            return "break"

        def copy_selection(_event=None):
            try:
                selected = text_widget.get("sel.first", "sel.last")
            except tk.TclError:
                return "break"
            root.clipboard_clear()
            root.clipboard_append(selected)
            root.update()
            return "break"

        def copy_all() -> None:
            root.clipboard_clear()
            root.clipboard_append(text)
            root.update()

        def new_button(label: str, command):
            return tk.Button(
                button_bar,
                text=label,
                command=command,
                bg=palette["button"],
                fg=palette["text"],
                activebackground=palette["button_active"],
                activeforeground=palette["text"],
                relief="flat",
                borderwidth=0,
                padx=14,
                pady=7,
                font=("Segoe UI", 9),
                cursor="hand2",
            )

        new_button("Kopiera allt", copy_all).pack(side="left")
        new_button("Stäng", root.destroy).pack(side="right")

        text_widget.bind("<Control-a>", select_all)
        text_widget.bind("<Control-A>", select_all)
        text_widget.bind("<Control-c>", copy_selection)
        text_widget.bind("<Control-C>", copy_selection)
        root.bind("<Escape>", lambda _event: root.destroy())
        text_widget.focus_set()

        root.mainloop()

    thread = threading.Thread(target=run_window, name="TradeAlertInfoWindow", daemon=True)
    thread.start()


class TrayController:
    def __init__(self, config: Config):
        self.config = config
        self._native_menu_theme = configure_windows_native_menu_theme(config.theme_mode)
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
                pystray.MenuItem(
                    "Tema",
                    pystray.Menu(
                        pystray.MenuItem(
                            _THEME_LABELS["system"],
                            self._set_theme("system"),
                            checked=self._theme_checked("system"),
                            radio=True,
                        ),
                        pystray.MenuItem(
                            _THEME_LABELS["light"],
                            self._set_theme("light"),
                            checked=self._theme_checked("light"),
                            radio=True,
                        ),
                        pystray.MenuItem(
                            _THEME_LABELS["dark"],
                            self._set_theme("dark"),
                            checked=self._theme_checked("dark"),
                            radio=True,
                        ),
                    ),
                ),
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
        self.icon.run(setup=self._tray_ready)

    def _tray_ready(self, icon) -> None:
        for attr in ("_hwnd", "_menu_hwnd"):
            allow_windows_dark_mode_for_window(
                getattr(icon, attr, None),
                self.config.theme_mode,
            )
        flush_windows_menu_themes()

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

    def _theme_checked(self, mode: str):
        return lambda _item: self.config.theme_mode == mode

    def _set_theme(self, mode: str):
        def handler(_icon, _item) -> None:
            self.config.theme_mode = mode
            self.config.save()

            self._native_menu_theme = configure_windows_native_menu_theme(mode)
            for attr in ("_hwnd", "_menu_hwnd"):
                allow_windows_dark_mode_for_window(
                    getattr(self.icon, attr, None),
                    mode,
                )

            # Recreate the native HMENU after changing PreferredAppMode, then
            # flush Windows' cached menu visuals so the next right-click uses
            # the selected theme.
            self.icon.update_menu()
            flush_windows_menu_themes()

        return handler

    def _toggle_pause(self, _icon, _item) -> None:
        if self.pause_event.is_set():
            self.pause_event.clear()
            self._set_status("Återupptar…", "waiting")
        else:
            self.pause_event.set()
            self._set_status("Pausad", "paused")

    def _show_monitoring(self, _icon, _item) -> None:
        store = StateStore()
        try:
            cached_id = store.get_meta("dtv_watchlist_id")
            cached_name = store.get_meta("dtv_watchlist_name")
        finally:
            store.close()

        text = monitoring_summary(
            self.config,
            resolved_watchlist_name=cached_name,
            auto_pinned_watchlist=bool(cached_id and not self.config.dtv_watchlist_id),
        )
        _show_text_window("Trade Alert · Vad bevakas?", text, self.config.theme_mode)

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
        _show_text_window("Trade Alert · Senaste alerts", text, self.config.theme_mode)

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
