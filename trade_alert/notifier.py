from __future__ import annotations

import logging
import os


def notify(title: str, body: str) -> bool:
    """Show a local notification and report whether the notification API accepted it."""
    if os.name != "nt":
        print(f"[{title}] {body}")
        return True

    try:
        from windows_toasts import Toast, WindowsToaster

        toaster = WindowsToaster("Trade Alert")
        toast = Toast()
        toast.text_fields = [str(title), str(body)]
        toaster.show_toast(toast)
        return True
    except Exception:
        logging.exception("Windows notification failed")
        return False
