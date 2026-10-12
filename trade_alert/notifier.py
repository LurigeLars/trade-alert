from __future__ import annotations

import hashlib
import logging
import os
import threading
import webbrowser
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

from .config import Config
from .news import normalize_news_link
from .state import MAX_ALERT_HISTORY, StateStore


# shortcut: callbacks survive only while this process runs; cold activation needs a packaged app.
_active_toasts: OrderedDict[str, tuple[object, object]] = OrderedDict()
_toast_lock = threading.Lock()


def alert_click(path: Path, item_key: str, on_read: Callable[[int], None] | None = None):
    def click() -> bool:
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
            if not webbrowser.open_new_tab(url):
                logging.error('Browser rejected alert URL; alert remains unread')
                return False
            mark_read()
        else:
            from .tray import _show_text_window, format_alert_history, make_window_icon

            _show_text_window(
                'Trade Alert · Senaste alerts',
                format_alert_history([alert], unread_count),
                Config.load().theme_mode,
                make_window_icon(),
                on_shown=mark_read,
            )
        return True
    return click


def _windows_toaster():
    import winreg
    from windows_toasts import WindowsToaster

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, r'Software\Classes\AppUserModelId\Trade Alert') as key:
        winreg.SetValueEx(key, 'DisplayName', 0, winreg.REG_SZ, 'Trade Alert')
    return WindowsToaster('Trade Alert')


def notify(title: str, body: str, *, on_click: Callable[[], bool] | None = None,
           item_key: str | None = None) -> bool:
    """Report API submission, which does not guarantee Windows displayed a banner."""
    if os.name != 'nt':
        print(f'[{title}] {body}')
        return True
    try:
        from windows_toasts import Toast
        from winrt.windows.ui.notifications import ToastNotification

        toaster = _windows_toaster()
        toast = Toast()
        toast.text_fields = [str(title), str(body)]
        # The library's show_toast drops the native object and loses click delivery.
        native = ToastNotification(toaster._setup_toast(toast, False).xmlDocument)
        native.tag = hashlib.sha256(item_key.encode('utf-8')).hexdigest()[:16] if item_key else toast.tag
        native.group = 'alerts'
        native.add_failed(lambda _sender, _event: logging.error('Windows failed to display Trade Alert toast'))
        if on_click is not None:
            click_lock = threading.Lock()
            handled = False

            def activated(_sender, _event):
                def run():
                    nonlocal handled
                    with click_lock:
                        if handled:
                            return
                        try:
                            handled = bool(on_click())
                        except Exception:
                            logging.exception('Alert click failed; acknowledgement not confirmed')
                threading.Thread(target=run, name='TradeAlertClick', daemon=True).start()

            native.add_activated(activated)
        with _toast_lock:
            toaster.toastNotifier.show(native)
            if on_click is not None:
                _active_toasts[native.tag] = (native, toaster)
                _active_toasts.move_to_end(native.tag)
                while len(_active_toasts) > MAX_ALERT_HISTORY:
                    _active_toasts.popitem(last=False)
        return True
    except Exception:
        logging.exception('Windows notification failed')
        return False
