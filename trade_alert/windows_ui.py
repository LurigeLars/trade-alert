from __future__ import annotations

import ctypes
import os

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
PROCESS_PER_MONITOR_DPI_AWARE = 2
ERROR_ACCESS_DENIED = 5
E_ACCESSDENIED = 0x80070005


def configure_windows_dpi_awareness() -> str:
    """Set process DPI awareness before any Windows UI is created.

    Prefer Per-Monitor V2 on modern Windows. Fall back to the older
    per-monitor and system-aware APIs when needed. If awareness was already
    configured by a manifest or another component, leave it unchanged.
    """
    if os.name != "nt":
        return "not-windows"

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        set_context = getattr(user32, "SetProcessDpiAwarenessContext", None)
        if set_context is not None:
            set_context.argtypes = [ctypes.c_void_p]
            set_context.restype = ctypes.c_bool
            ctypes.set_last_error(0)
            context = ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
            if set_context(context):
                return "per-monitor-v2"
            if ctypes.get_last_error() == ERROR_ACCESS_DENIED:
                return "already-set"
    except (AttributeError, OSError):
        pass

    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        set_awareness = getattr(shcore, "SetProcessDpiAwareness", None)
        if set_awareness is not None:
            set_awareness.argtypes = [ctypes.c_int]
            set_awareness.restype = ctypes.c_long
            result = int(set_awareness(PROCESS_PER_MONITOR_DPI_AWARE)) & 0xFFFFFFFF
            if result == 0:
                return "per-monitor"
            if result == E_ACCESSDENIED:
                return "already-set"
    except (AttributeError, OSError):
        pass

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        set_aware = getattr(user32, "SetProcessDPIAware", None)
        if set_aware is not None:
            set_aware.argtypes = []
            set_aware.restype = ctypes.c_bool
            if set_aware():
                return "system-aware"
            if ctypes.get_last_error() == ERROR_ACCESS_DENIED:
                return "already-set"
    except (AttributeError, OSError):
        pass

    return "unavailable"
