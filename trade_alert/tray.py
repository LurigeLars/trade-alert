from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, Literal

import pystray
from PIL import Image, ImageDraw

from dataclasses import replace

from .config import Config, Watch, app_dir
from .news import CORE_TERM_LABELS, IMPACT_TERM_LABELS, OIL_ROUTING_SYMBOLS, normalize_news_link
from .state import MAX_ALERT_HISTORY, AlertRecord, StateStore
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


def make_window_icon() -> Image.Image:
    """Window/taskbar branding, independent of live health and unread state.

    Windows may cache the first Tk window icon under the app's stable
    AppUserModelID; rendering transient warning/badge states in a window icon
    would then misrepresent the status after a recovery or after reading alerts.
    Only the system-tray icon conveys the live state.
    """
    return make_status_icon("ok", unread=0)


def save_static_shortcut_icon(path: str | Path) -> Path:
    """Save the base Trade Alert tray artwork as a Windows shortcut icon.

    The static shortcut uses the healthy green motif without the transient
    unread badge. Its image is generated locally, never stored in the repo.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    make_status_icon("ok", unread=0).save(
        target,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)],
    )
    return target


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

    watch_lines = "".join(f"• {watch_label(watch)}\n" for watch in config.watches) or "• inga\n"
    return (
        f"Profil\n{config.profile_name}\n\n"
        f"Bevakningar\n"
        f"• Oljebevakning: {'på' if config.oil_watch_enabled else 'av'}\n"
        f"{watch_lines}"
        f"  ändras under Inställningar… eller i config.json; gäller inom {config.poll_seconds} s\n\n"
        f"Källor\n"
        f"• DTV TradingView News Flow: PRIMÄR · broad discovery\n"
        f"  {dtv_context}\n"
        f"• Official TradingView symbol-news: SEKUNDÄR · targeted corroboration\n"
        f"  {symbols}\n"
        f"• Chrome lokal överföring: {'påslagen' if config.chrome_bridge_enabled else 'avstängd'}\n"
        f"  läser enbart lokalt nedladdade filer; sidan måste vara öppen\n"
        f"• Direkt Truth Social: {'konfigurerad (åtkomst ej verifierad)' if config.truth_direct_enabled else 'avstängd'}\n"
        f"  var {config.truth_direct_poll_seconds} s; anonym offentlig API, stopp vid 401/403/429\n"
        f"• Trump's Truth RSS: {'konfigurerad tredjepartskälla' if config.truth_rss_enabled else 'avstängd'}\n"
        f"  var {config.truth_rss_poll_seconds} s · arkivet uppdateras enligt egen uppgift med flera minuters intervall\n"
        f"• Policy hot path: {'lokalt aktiverad' if config.breaking_inbox_enabled else 'avstängd'}\n"
        f"  {len(config.breaking_authorized_sources)} godkända käll-ID:n; "
        f"{'ingen ansluten livekälla' if not config.breaking_authorized_sources else 'inbox-bevakning aktiv, upstream ej automatiskt verifierad'}\n\n"
        f"Polling\n"
        f"• News Flow: var {config.poll_seconds} s · max {config.dtv_max_headlines} headlines\n"
        f"• News Flow replay-overlap: {config.dtv_replay_overlap_seconds} s för sena/backfillade stories\n"
        f"• Official TradingView: var {config.official_poll_seconds} s · "
        f"max {config.official_max_headlines} headlines/symbol\n\n"
        f"Alertfilter\n"
        f"• relevanspoäng ≥ {config.notification_min_score}\n"
        f"• +2 för explicit olje/core-term i rubriken:\n  {', '.join(CORE_TERM_LABELS)}\n"
        f"• +2 för impact-term ENDAST när oljecontext finns:\n  {', '.join(IMPACT_TERM_LABELS)}\n"
        f"• +1 för olje-relaterad provider-symbol (routing evidence, räcker aldrig ensam)\n"
        f"• +1 för TradingView urgency = 1, endast när oljecontext finns\n"
        f"• routing-symboler: {routing}\n\n"
        f"Varje appstart\n"
        f"• inlägg publicerade före uppstart sparas som lästa i historiken utan Windows-notis\n"
        f"• bara den senast publicerade händelsen per 5 s-körning notifieras; minst 60 s mellan banners\n"
        f"• första News Flow-aktiveringen baselinar dessutom äldre rubriker än {config.startup_fresh_seconds} s\n"
        f"• watchlist-ID sparas endast lokalt i Trade Alert-state; inget konto-ID committas\n\n"
        f"Modell\n"
        f"• ingen LLM används i hot path"
    )


def _local_timestamp(value: float | None) -> str:
    if value is None:
        return "okänd"
    try:
        return datetime.fromtimestamp(value).astimezone().strftime("%H:%M %d/%m")
    except (OSError, OverflowError, ValueError):
        return "okänd"


def format_alert_history(
    alerts: list[AlertRecord], unread_count: int,
) -> tuple[str, list[tuple[int, str, str]]]:
    if not alerts:
        return "Inga riktiga Trade Alert-signaler har registrerats ännu.", []

    lines = [f"Olästa före öppning: {unread_count}", "", f"Senaste {len(alerts)} alerts:"]
    links = []
    for alert in alerts:
        published = _local_timestamp(alert.published)
        marker = "OLÄST" if alert.unread else "läst"
        provider = " ".join((alert.provider or alert.source).split())
        prefix = f"{provider} · "
        headline = " ".join(alert.headline.split())
        lines.extend(["", f"[{marker}] {published}", prefix + headline])
        url = normalize_news_link(alert.link)
        if url is not None and headline:
            links.append((len(lines), prefix, url))
    return "\n".join(lines), links


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
            "link": "#4cc2ff",
            "link_hover": "#60cdff",
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
        "link": "#0067c0",
        "link_hover": "#004578",
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


def _layout_information_panes(outer, content, footer) -> None:
    """Reserve a fixed bottom row before allocating expandable text area.

    The old sequential pack layout could clip the footer at some Windows
    scaling factors: the 24-line Text request consumed the entire height.
    """
    outer.grid_rowconfigure(0, weight=1)
    outer.grid_rowconfigure(1, weight=0)
    outer.grid_columnconfigure(0, weight=1)
    content.grid(row=0, column=0, sticky="nsew")
    footer.grid(row=1, column=0, sticky="ew")


def _show_text_window(
    title: str,
    text: str,
    theme_mode: str,
    app_icon: Image.Image | None = None,
    *,
    show_all_label: str | None = None,
    on_show_all: Callable[[], tuple[str, list[tuple[int, str, str]]]] | None = None,
    on_shown: Callable[[], None] | None = None,
    links: list[tuple[int, str, str]] | None = None,
) -> None:
    """Open a selectable, copyable information window using the effective theme."""
    if os.name != "nt":
        logging.info("%s\n%s", title, text)
        return

    def run_window() -> None:
        import tkinter as tk
        from PIL import ImageTk

        theme = resolve_theme(theme_mode)
        palette = theme_palette(theme)

        root = tk.Tk()
        root.title(title)
        if app_icon is not None:
            # Keep a reference for the lifetime of this Tk interpreter.
            root._trade_alert_icon = ImageTk.PhotoImage(app_icon)  # type: ignore[attr-defined]
            root.iconphoto(True, root._trade_alert_icon)  # type: ignore[attr-defined]
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
        button_bar = tk.Frame(outer, bg=palette["window"], pady=10)
        _layout_information_panes(outer, text_frame, button_bar)

        scrollbar = tk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")

        text_widget = tk.Text(
            text_frame,
            wrap="word",
            yscrollcommand=scrollbar.set,
            height=1,  # Let the resizable grid row decide the text area height.
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

        current_text = text

        def render_text(content: str, content_links: list[tuple[int, str, str]] | None = None) -> None:
            nonlocal current_text
            current_text = content
            text_widget.configure(state="normal")
            text_widget.delete("1.0", "end")
            for old_tag in text_widget.tag_names():
                if old_tag.startswith("hyperlink_"):
                    text_widget.tag_delete(old_tag)
            text_widget.insert("1.0", current_text)

            headings = {"Profil", "Bevakningar", "Källor", "Polling", "Alertfilter", "Första News Flow-start", "Modell"}
            text_widget.tag_configure("heading", font=("Segoe UI Semibold", 10))
            for line_number, line in enumerate(current_text.splitlines(), start=1):
                if line.strip() in headings:
                    text_widget.tag_add("heading", f"{line_number}.0", f"{line_number}.end")

            for link_number, (line_number, prefix, browser_url) in enumerate(content_links or []):
                tag = f"hyperlink_{link_number}"
                # Tcl counts supplementary Unicode characters differently from Python.
                column = text_widget.tk.call("string", "length", prefix)
                start = f"{line_number}.{column}"
                end = f"{line_number}.end"
                text_widget.tag_add(tag, start, end)
                text_widget.tag_configure(
                    tag,
                    foreground=palette["link"],
                    underline=True,
                )

                def open_link(_event, url=browser_url):
                    webbrowser.open_new_tab(url)
                    return "break"

                def link_enter(_event, name=tag):
                    text_widget.configure(cursor="hand2")
                    text_widget.tag_configure(name, foreground=palette["link_hover"])

                def link_leave(_event, name=tag):
                    text_widget.configure(cursor="xterm")
                    text_widget.tag_configure(name, foreground=palette["link"])

                text_widget.tag_bind(tag, "<Button-1>", open_link)
                text_widget.tag_bind(tag, "<Enter>", link_enter)
                text_widget.tag_bind(tag, "<Leave>", link_leave)

            text_widget.configure(state="disabled")
            text_widget.yview_moveto(0.0)

        render_text(text, links)

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
            root.clipboard_append(current_text)
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
        if on_show_all is not None:
            def expand_history() -> None:
                try:
                    expanded_text = on_show_all()
                except Exception:
                    logging.exception("Could not expand Trade Alert history")
                    return
                render_text(*expanded_text)
                if on_shown is not None:
                    on_shown()
                show_all_button.destroy()

            show_all_button = new_button(show_all_label or "Visa alla", expand_history)
            show_all_button.pack(side="left", padx=(8, 0))
        new_button("Stäng", root.destroy).pack(side="right")

        text_widget.bind("<Control-a>", select_all)
        text_widget.bind("<Control-A>", select_all)
        text_widget.bind("<Control-c>", copy_selection)
        text_widget.bind("<Control-C>", copy_selection)
        root.bind("<Escape>", lambda _event: root.destroy())
        text_widget.focus_set()

        if on_shown is not None:
            def shown(_event) -> None:
                if _event.widget is root:
                    root.unbind("<Map>")
                    try:
                        on_shown()
                    except Exception:
                        logging.exception("Could not acknowledge displayed alert")
            root.bind("<Map>", shown)
        root.mainloop()

    thread = threading.Thread(target=run_window, name="TradeAlertInfoWindow", daemon=True)
    thread.start()


SOURCE_TOGGLES = (
    ("oil_watch_enabled", "Oljebevakning (inbyggda oljeregler i News Flow)"),
    ("truth_rss_enabled", "Trump via Truth-RSS"),
    ("chrome_bridge_enabled", "Trump via Chrome-tillägget"),
    ("truth_direct_enabled", "Truth Social direkt (blockeras ofta med 403)"),
)


def parse_terms(text: str) -> tuple[str, ...]:
    """Comma- or newline-separated input → unique, trimmed terms in typed order."""
    parts = (part.strip() for part in text.replace("\n", ",").split(","))
    return tuple(dict.fromkeys(part for part in parts if part))


def watch_label(watch: Watch) -> str:
    state = "PÅ" if watch.enabled else "AV"
    details = []
    if watch.keywords:
        details.append("ord: " + ", ".join(watch.keywords))
    if watch.symbols:
        details.append("symboler: " + ", ".join(watch.symbols))
    return f"[{state}] {watch.name} — " + " · ".join(details)


def apply_settings(config: Config, toggles: dict[str, bool], watches: list[Watch]) -> None:
    """Validate the window's values, then update the shared config and config.json together."""
    unknown = set(toggles) - {name for name, _label in SOURCE_TOGGLES}
    if unknown:
        raise ValueError(f"unknown settings: {', '.join(sorted(unknown))}")
    candidate = replace(config, **toggles, watches=tuple(watches))
    candidate.validate()
    config.update_from(candidate)
    config.save()


def _show_settings_window(config: Config, watchlist_label: str, app_icon: Image.Image | None = None) -> None:
    if os.name != "nt":
        logging.info("Settings window is only available on Windows")
        return

    def run_window() -> None:
        import tkinter as tk
        from tkinter import messagebox
        from PIL import ImageTk

        theme = resolve_theme(config.theme_mode)
        palette = theme_palette(theme)
        root = tk.Tk()
        root.title("Trade Alert · Inställningar")
        if app_icon is not None:
            root._trade_alert_icon = ImageTk.PhotoImage(app_icon)  # type: ignore[attr-defined]
            root.iconphoto(True, root._trade_alert_icon)  # type: ignore[attr-defined]
        # The app is per-monitor DPI aware, so pixel sizes must follow the display scaling.
        scale = max(1.0, root.winfo_fpixels("1i") / 96)
        root.geometry(f"{int(780 * scale)}x{int(600 * scale)}")
        root.minsize(int(600 * scale), int(480 * scale))
        root.configure(bg=palette["window"])
        _apply_windows_titlebar_theme(root, dark=theme == "dark")

        def label(parent, text, *, heading=False, muted=False):
            widget = tk.Label(
                parent, text=text, anchor="w", justify="left",
                bg=palette["window"], fg=palette["muted" if muted else "text"],
                font=("Segoe UI Semibold", 10) if heading else ("Segoe UI", 9),
            )
            widget.bind("<Configure>", lambda e: e.widget.configure(wraplength=max(100, e.width - 4)))
            return widget

        def button(parent, text, command):
            return tk.Button(
                parent, text=text, command=command, bg=palette["button"], fg=palette["text"],
                activebackground=palette["button_active"], activeforeground=palette["text"],
                relief="flat", borderwidth=0, padx=12, pady=6, font=("Segoe UI", 9), cursor="hand2",
            )

        outer = tk.Frame(root, bg=palette["window"], padx=16, pady=14)
        outer.pack(fill="both", expand=True)
        # Bottom rows are packed first so the expanding list can never push them out of view.
        footer = tk.Frame(outer, bg=palette["window"], pady=10)
        footer.pack(fill="x", side="bottom")
        status = label(outer, "", muted=True)
        status.pack(fill="x", side="bottom")

        label(outer, "Källor", heading=True).pack(fill="x")
        toggle_vars = {name: tk.BooleanVar(value=getattr(config, name)) for name, _ in SOURCE_TOGGLES}
        for name, text in SOURCE_TOGGLES:
            tk.Checkbutton(
                outer, text=text, variable=toggle_vars[name], anchor="w",
                bg=palette["window"], fg=palette["text"], selectcolor=palette["surface"],
                activebackground=palette["window"], activeforeground=palette["text"],
                font=("Segoe UI", 9),
            ).pack(fill="x")
        label(outer, f"Nyheter hämtas från TradingView-listan {watchlist_label}. "
                     "Bevakningar matchar bara nyheter om symbolerna i den listan.",
              muted=True).pack(fill="x", pady=(4, 12))

        label(outer, "Egna bevakningar", heading=True).pack(fill="x")
        label(outer, "Larmar när ett sökord står i rubriken eller nyheten gäller en av symbolerna.",
              muted=True).pack(fill="x")

        watches: list[Watch] = list(config.watches)
        list_bar = tk.Frame(outer, bg=palette["window"])
        list_bar.pack(fill="x", side="bottom")
        list_frame = tk.Frame(outer, bg=palette["surface"], highlightbackground=palette["border"],
                              highlightthickness=1)
        list_frame.pack(fill="both", expand=True, pady=(6, 6))
        listbox = tk.Listbox(
            list_frame, bg=palette["surface"], fg=palette["text"], relief="flat", borderwidth=0,
            highlightthickness=0, selectbackground=palette["selection"],
            selectforeground=palette["selection_text"], font=("Segoe UI", 9), activestyle="none",
        )
        listbox.pack(fill="both", expand=True, padx=6, pady=6)

        def refresh() -> None:
            listbox.delete(0, "end")
            for watch in watches:
                listbox.insert("end", watch_label(watch))

        def selected() -> int | None:
            picked = listbox.curselection()
            return picked[0] if picked else None

        def edit(index: int | None) -> None:
            current = watches[index] if index is not None else Watch(name="")
            dialog = tk.Toplevel(root)
            dialog.title("Bevakning")
            dialog.configure(bg=palette["window"], padx=14, pady=12)
            dialog.transient(root)
            dialog.grab_set()
            entries = {}
            fields_spec = (
                ("name", "Namn", current.name),
                ("keywords", "Sökord (kommaseparerade)", ", ".join(current.keywords)),
                ("symbols", "Symboler, t.ex. NASDAQ:MSFT (kommaseparerade)", ", ".join(current.symbols)),
            )
            for key, text, value in fields_spec:
                label(dialog, text).pack(fill="x")
                entry = tk.Entry(dialog, width=60, bg=palette["surface"], fg=palette["text"],
                                 insertbackground=palette["text"], relief="flat", font=("Segoe UI", 9))
                entry.insert(0, value)
                entry.pack(fill="x", pady=(2, 8), ipady=3)
                entries[key] = entry

            def accept() -> None:
                candidate = Watch(
                    name=entries["name"].get().strip(),
                    keywords=parse_terms(entries["keywords"].get()),
                    symbols=tuple(s.upper() for s in parse_terms(entries["symbols"].get())),
                    enabled=current.enabled,
                )
                try:
                    candidate.validate()
                    others = [w.name.casefold() for i, w in enumerate(watches) if i != index]
                    if candidate.name.casefold() in others:
                        raise ValueError("det finns redan en bevakning med det namnet")
                except ValueError as exc:
                    messagebox.showerror("Bevakning", str(exc), parent=dialog)
                    return
                if index is None:
                    watches.append(candidate)
                else:
                    watches[index] = candidate
                refresh()
                dialog.destroy()

            bar = tk.Frame(dialog, bg=palette["window"])
            bar.pack(fill="x", pady=(4, 0))
            button(bar, "Avbryt", dialog.destroy).pack(side="right")
            button(bar, "OK", accept).pack(side="right", padx=(0, 8))
            entries["name"].focus_set()
            dialog.bind("<Return>", lambda _e: accept())
            dialog.bind("<Escape>", lambda _e: dialog.destroy())

        def toggle() -> None:
            index = selected()
            if index is not None:
                watches[index] = replace(watches[index], enabled=not watches[index].enabled)
                refresh()
                listbox.selection_set(index)

        def remove() -> None:
            index = selected()
            if index is not None and messagebox.askyesno(
                    "Ta bort", f"Ta bort bevakningen {watches[index].name}?", parent=root):
                del watches[index]
                refresh()

        button(list_bar, "Lägg till", lambda: edit(None)).pack(side="left")
        button(list_bar, "Ändra", lambda: selected() is not None and edit(selected())).pack(side="left", padx=(8, 0))
        button(list_bar, "Slå på/av", toggle).pack(side="left", padx=(8, 0))
        button(list_bar, "Ta bort", remove).pack(side="left", padx=(8, 0))
        listbox.bind("<Double-Button-1>", lambda _e: selected() is not None and edit(selected()))

        def save() -> None:
            try:
                apply_settings(config, {n: v.get() for n, v in toggle_vars.items()}, watches)
            except (OSError, ValueError) as exc:
                messagebox.showerror("Kunde inte spara", str(exc), parent=root)
                return
            logging.info("Settings saved from the settings window")
            status.configure(text="Sparat. Gäller direkt.")

        button(footer, "Stäng", root.destroy).pack(side="right")
        button(footer, "Spara", save).pack(side="right", padx=(0, 8))
        root.bind("<Escape>", lambda _e: root.destroy())
        refresh()
        root.mainloop()

    threading.Thread(target=run_window, name="TradeAlertSettingsWindow", daemon=True).start()


class TrayController:
    def __init__(
        self,
        config: Config,
        monitor_loop: Callable[..., Awaitable[None]],
        log_path: Path,
        send_notification: Callable[[str, str], bool],
    ):
        self.config = config
        # Inject the toast sender from app.py; tray must not import notifier.
        self._send_notification = send_notification
        self._monitor_loop = monitor_loop
        self._log_path = log_path
        self._native_menu_theme = configure_windows_native_menu_theme(config.theme_mode)
        logging.info("Windows native tray menu theme: %s", self._native_menu_theme)
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self._status = "Startar…"
        self._health: Health = "waiting"
        self._unread_count = self._load_unread_count()
        self.icon = pystray.Icon(
            "Trade Alert",
            icon=make_status_icon("waiting", self._unread_count),
            title=self._tooltip(),
            menu=self._build_menu(),
        )
        self.worker = threading.Thread(
            target=self._worker_main,
            name="TradeAlertMonitor",
            daemon=True,
        )

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
                pystray.MenuItem(lambda _item: self._status_line(), None, enabled=False),
                pystray.MenuItem(
                    lambda _item: self._alerts_label(),
                    self._show_alert_history,
                    default=True,
                ),
                pystray.MenuItem("Vad bevakas?", self._show_monitoring),
                pystray.MenuItem("Inställningar…", self._show_settings),
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
        icon.visible = True

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
                self._monitor_loop(
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
        _show_text_window(
            "Trade Alert · Vad bevakas?",
            text,
            self.config.theme_mode,
            make_window_icon(),
        )

    def _show_settings(self, _icon, _item) -> None:
        store = StateStore()
        try:
            name = store.get_meta("dtv_watchlist_name") or "namn okänt"
            watchlist_id = self.config.dtv_watchlist_id or store.get_meta("dtv_watchlist_id") or "ej vald"
        finally:
            store.close()
        _show_settings_window(self.config, f"\"{name}\" (id {watchlist_id})", make_window_icon())

    def _show_alert_history(self, _icon, _item) -> None:
        store = StateStore()
        try:
            unread_before = store.unread_alert_count()
            alerts = store.recent_alerts(limit=MAX_ALERT_HISTORY)
            visible = alerts[:10]
            text, links = format_alert_history(visible, unread_before)
        finally:
            store.close()

        def show_all() -> tuple[str, list[tuple[int, str, str]]]:
            nonlocal visible
            visible = alerts
            return format_alert_history(alerts, unread_before)

        def shown() -> None:
            displayed_store = StateStore()
            try:
                displayed_store.mark_alerts_read([alert.item_key for alert in visible])
                self._unread_count = displayed_store.unread_alert_count()
            finally:
                displayed_store.close()
            self._refresh_tray()

        _show_text_window(
            "Trade Alert · Senaste alerts",
            text,
            self.config.theme_mode,
            make_window_icon(),
            show_all_label=f"Visa alla {len(alerts)}" if len(alerts) > 10 else None,
            on_show_all=show_all if len(alerts) > 10 else None,
            on_shown=shown,
            links=links,
        )

    def _test_notification(self, _icon, _item) -> None:
        previous_status = self._status
        previous_health = self._health
        if self._send_notification("Trade Alert", "Tray-appen fungerar."):
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
            logging.info("Logg: %s", self._log_path)

    def _exit(self, icon, _item) -> None:
        self.stop_event.set()
        icon.stop()


def run_tray(
    config: Config,
    monitor_loop: Callable[..., Awaitable[None]],
    log_path: Path,
    send_notification: Callable[[str, str], bool],
) -> None:
    TrayController(config, monitor_loop, log_path, send_notification).run()
