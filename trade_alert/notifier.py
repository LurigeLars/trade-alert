from __future__ import annotations

import hashlib
import logging
import math
import os
import time
import secrets
import threading
import webbrowser
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import Config
from .news import normalize_news_link
from .state import MAX_ALERT_HISTORY, StateStore


# shortcut: click links work while the sender runs; cold activation needs a packaged app.
_click_actions: OrderedDict[str, tuple[Callable, threading.Lock]] = OrderedDict()
_click_server: ThreadingHTTPServer | None = None
_toast_lock = threading.Lock()


class _ClickHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # Do not put one-use tokens in access logs.

    def do_GET(self):
        if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
            self.send_error(403)
            return
        with _toast_lock:
            action = _click_actions.get(self.path)
        if action is None:
            self.send_error(410, 'Alert click link expired')
            return
        callback, lock = action
        responded = False

        def respond(status, url=None):
            nonlocal responded
            self.send_response(status)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', '0')
            if url is not None:
                self.send_header('Location', url)
            self.end_headers()
            self.wfile.flush()
            responded = True
            return True

        with lock:
            with _toast_lock:
                pending = self.path in _click_actions
            if not pending:
                respond(410)
                return
            try:
                if callback(lambda url: respond(303, url)):
                    with _toast_lock:
                        _click_actions.pop(self.path, None)
                    if not responded:
                        respond(204)  # A missing article URL opened the matching history window.
                elif not responded:
                    respond(410)
            except Exception:
                logging.exception('Alert click failed; acknowledgement not confirmed')
                if not responded:
                    respond(500)


def _click_url(callback: Callable) -> str:
    global _click_server
    with _toast_lock:
        if _click_server is None:
            _click_server = ThreadingHTTPServer(('127.0.0.1', 0), _ClickHandler)
            threading.Thread(target=_click_server.serve_forever, name='TradeAlertClicks', daemon=True).start()
        path = '/alerts/' + secrets.token_urlsafe(24)
        _click_actions[path] = (callback, threading.Lock())
        while len(_click_actions) > MAX_ALERT_HISTORY:
            _click_actions.popitem(last=False)
        return f'http://127.0.0.1:{_click_server.server_port}{path}'


def alert_click(path: Path, item_key: str, on_read: Callable[[int], None] | None = None):
    def click(open_article: Callable[[str], bool] | None = None) -> bool:
        store = StateStore(path)
        try:
            alert = next((a for a in store.recent_alerts() if a.item_key == item_key), None)
            unread_count = store.unread_alert_count()
        finally:
            store.close()
        if alert is None:
            logging.warning('Clicked alert is no longer in history')
            return False

        def mark_read() -> None:
            current = StateStore(path)
            try:
                current.mark_alerts_read([item_key])
                count = current.unread_alert_count()
            finally:
                current.close()
            if on_read is not None:
                try:
                    on_read(count)
                except Exception:
                    logging.exception('Could not refresh unread badge')

        url = normalize_news_link(alert.link)
        if url is not None:
            if not (open_article or webbrowser.open_new_tab)(url):
                logging.error('Browser rejected alert URL; alert remains unread')
                return False
            mark_read()
        else:
            from .tray import _show_text_window, format_alert_history, make_window_icon

            text, links = format_alert_history([alert], unread_count)
            _show_text_window(
                'Trade Alert · Senaste alerts',
                text,
                Config.load().theme_mode,
                make_window_icon(),
                on_shown=mark_read,
                links=links,
            )
        return True
    return click


def _windows_toaster():
    import winreg
    from windows_toasts import WindowsToaster

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, r'Software\Classes\AppUserModelId\Trade Alert') as key:
        winreg.SetValueEx(key, 'DisplayName', 0, winreg.REG_SZ, 'Trade Alert')
    return WindowsToaster('Trade Alert')


# Only one alert per burst is presented to Windows. The rest stay in SQLite history.
BURST_COLLECT_SECONDS = 5.0
BURST_COOLDOWN_SECONDS = 60.0


@dataclass(frozen=True)
class _PendingNotification:
    title: str
    body: str
    item_key: str
    on_click: Callable | None
    published_at: float | None

    @property
    def sort_key(self) -> float:
        if self.published_at is None:
            return -math.inf
        try:
            value = float(self.published_at)
        except (ValueError, TypeError):
            return -math.inf
        return value if math.isfinite(value) else -math.inf


class _NotificationBurst:
    """Thread-safe, process-local cross-source coalescer.

    Collect the first five seconds of a burst and send the latest *published*
    event. Any further burst within a minute is held until the cooldown ends;
    an old candidate is replaced by a later-published alert. All callers have
    already written their own history and deduplication state.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: _PendingNotification | None = None
        self._timer: threading.Timer | None = None
        self._last_delivery = -math.inf

    def offer(self, candidate: _PendingNotification) -> bool:
        with self._lock:
            if self._pending is None or candidate.sort_key >= self._pending.sort_key:
                self._pending = candidate
            if self._timer is None:
                delay = max(
                    BURST_COLLECT_SECONDS,
                    self._last_delivery + BURST_COOLDOWN_SECONDS - time.monotonic(),
                )
                self._timer = threading.Timer(delay, self.flush)
                self._timer.daemon = True
                self._timer.start()
        return True  # queued for possible delivery; not proof of toast display

    def flush(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            candidate, self._pending = self._pending, None
            self._timer = None
            if candidate is None:
                return
            self._last_delivery = time.monotonic()
        _notify_now(
            candidate.title, candidate.body,
            item_key=candidate.item_key, on_click=candidate.on_click,
        )

    def discard(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = None
            self._pending = None


_burst = _NotificationBurst()


def flush_pending_notifications() -> None:
    """One-shot commands can flush the most recent queued alert before exit."""
    _burst.flush()


def discard_pending_notifications() -> None:
    """Stop pending toast delivery when monitoring exits or closes."""
    _burst.discard()


def notify(title: str, body: str, *, on_click: Callable | None = None,
           item_key: str | None = None, published_at: float | None = None,
           coalesce: bool = True) -> bool:
    """Queue actionable Windows alerts by burst; tests remain immediate."""
    if os.name == 'nt' and item_key is not None and coalesce:
        return _burst.offer(_PendingNotification(
            str(title), str(body), item_key, on_click, published_at,
        ))
    return _notify_now(title, body, on_click=on_click, item_key=item_key)


def _notify_now(title: str, body: str, *, on_click: Callable | None = None,
                item_key: str | None = None) -> bool:
    """Submit one toast to Windows; acceptance does not ensure display."""
    if os.name != 'nt':
        print(f'[{title}] {body}')
        return True
    activation_url = None
    try:
        from windows_toasts import Toast

        toaster = _windows_toaster()
        toast = Toast()
        toast.text_fields = [str(title), str(body)]
        if item_key is not None:
            toast.tag = hashlib.sha256(item_key.encode('utf-8')).hexdigest()[:16]
        toast.group = 'alerts'
        if on_click is not None:
            activation_url = _click_url(on_click)
            toast.launch_action = activation_url
        toast.on_failed = lambda _event: logging.error('Windows failed to display Trade Alert toast')
        toaster.show_toast(toast)
        return True
    except Exception:
        if activation_url is not None:
            with _toast_lock:
                _click_actions.pop('/alerts/' + activation_url.rsplit('/', 1)[-1], None)
        logging.exception('Windows notification failed')
        return False
