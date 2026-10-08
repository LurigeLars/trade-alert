from __future__ import annotations

import ctypes
import logging
import os

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
PROCESS_PER_MONITOR_DPI_AWARE = 2
ERROR_ACCESS_DENIED = 5
E_ACCESSDENIED = 0x80070005
TRADE_ALERT_APP_USER_MODEL_ID = "LurigeLars.TradeAlert.Desktop"


def configure_windows_app_identity(
    app_id: str = TRADE_ALERT_APP_USER_MODEL_ID,
) -> str:
    """Give Trade Alert a stable Windows taskbar identity.

    pythonw.exe otherwise lends its executable identity/icon to Tk windows.
    Setting an explicit AppUserModelID before UI creation lets Windows group
    Trade Alert independently and use the window icon supplied by Tk.
    """
    if not app_id or len(app_id) > 128:
        raise ValueError("app_id must be between 1 and 128 characters")
    if os.name != "nt":
        return "not-windows"

    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        setter = getattr(shell32, "SetCurrentProcessExplicitAppUserModelID", None)
        if setter is None:
            return "unavailable"
        setter.argtypes = [ctypes.c_wchar_p]
        setter.restype = ctypes.c_long
        result = int(setter(app_id)) & 0xFFFFFFFF
        return "set" if result == 0 else f"hresult-0x{result:08x}"
    except (AttributeError, OSError):
        logging.debug("Windows AppUserModelID API unavailable", exc_info=True)
        return "unavailable"


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
        logging.debug("Windows DPI API unavailable; trying fallback", exc_info=True)

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
        logging.debug("Windows DPI API unavailable; trying fallback", exc_info=True)

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
        logging.debug("Windows DPI API unavailable; trying fallback", exc_info=True)

    return "unavailable"


WINDOWS_10_1903_BUILD = 18362
PREFERRED_APP_MODE_ALLOW_DARK = 1
PREFERRED_APP_MODE_FORCE_DARK = 2
PREFERRED_APP_MODE_FORCE_LIGHT = 3


def preferred_app_mode(theme_mode: str) -> int:
    """Map Trade Alert theme modes to the Win32 PreferredAppMode enum."""
    if theme_mode == "system":
        return PREFERRED_APP_MODE_ALLOW_DARK
    if theme_mode == "dark":
        return PREFERRED_APP_MODE_FORCE_DARK
    if theme_mode == "light":
        return PREFERRED_APP_MODE_FORCE_LIGHT
    raise ValueError("theme_mode must be system, light or dark")


def _windows_build_number() -> int:
    if os.name != "nt":
        return 0
    try:
        import sys

        return int(sys.getwindowsversion().build)
    except (AttributeError, TypeError, ValueError):
        return 0


def _uxtheme_ordinal(ordinal: int, restype, argtypes):
    """Resolve one private uxtheme export by ordinal.

    Windows still exposes its classic Win32 dark-menu opt-in only through
    private uxtheme exports. Resolve them dynamically and fail closed if the
    host build changes rather than binding them at import time.
    """
    if os.name != "nt":
        return None

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        kernel32.LoadLibraryW.argtypes = [ctypes.c_wchar_p]
        kernel32.LoadLibraryW.restype = ctypes.c_void_p
        kernel32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel32.GetProcAddress.restype = ctypes.c_void_p

        module = kernel32.GetModuleHandleW("uxtheme.dll")
        if not module:
            module = kernel32.LoadLibraryW("uxtheme.dll")
        if not module:
            return None

        address = kernel32.GetProcAddress(module, ctypes.c_void_p(ordinal))
        if not address:
            return None

        prototype = ctypes.WINFUNCTYPE(restype, *argtypes)
        return prototype(address)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def flush_windows_menu_themes() -> bool:
    """Refresh cached native menu visuals after a preferred app-mode change."""
    if os.name != "nt" or _windows_build_number() < WINDOWS_10_1903_BUILD:
        return False

    flush = _uxtheme_ordinal(136, None, ())
    if flush is None:
        return False
    try:
        flush()
        return True
    except (OSError, ValueError):
        return False


def configure_windows_native_menu_theme(theme_mode: str) -> str:
    """Apply Trade Alert's theme choice to native Win32 popup menus.

    system -> AllowDark (Windows decides)
    dark   -> ForceDark
    light  -> ForceLight

    The required Win32 menu dark-mode surface is private/ordinal-based on
    Windows 10/11. If it is unavailable, this function returns a status rather
    than breaking the tray app.
    """
    mode = preferred_app_mode(theme_mode)
    if os.name != "nt":
        return "not-windows"
    if _windows_build_number() < WINDOWS_10_1903_BUILD:
        return "unsupported"

    set_preferred = _uxtheme_ordinal(135, ctypes.c_int, (ctypes.c_int,))
    if set_preferred is None:
        return "unavailable"

    refresh_policy = _uxtheme_ordinal(104, None, ())
    try:
        if refresh_policy is not None:
            refresh_policy()
        set_preferred(mode)
        flushed = flush_windows_menu_themes()
    except (OSError, ValueError):
        return "unavailable"

    label = {
        PREFERRED_APP_MODE_ALLOW_DARK: "allow-dark",
        PREFERRED_APP_MODE_FORCE_DARK: "force-dark",
        PREFERRED_APP_MODE_FORCE_LIGHT: "force-light",
    }[mode]
    return label if flushed else f"{label}-no-flush"


def allow_windows_dark_mode_for_window(hwnd: int | None, theme_mode: str) -> bool:
    """Opt a pystray owner window into dark control theming when supported."""
    if (
        os.name != "nt"
        or not hwnd
        or _windows_build_number() < WINDOWS_10_1903_BUILD
    ):
        return False

    allow_dark = _uxtheme_ordinal(
        133,
        ctypes.c_bool,
        (ctypes.c_void_p, ctypes.c_bool),
    )
    if allow_dark is None:
        return False

    # AllowDarkModeForWindow is an opt-in. ForceLight explicitly disables it;
    # system/dark keep the window eligible and process PreferredAppMode decides.
    enabled = theme_mode != "light"
    try:
        return bool(allow_dark(ctypes.c_void_p(int(hwnd)), enabled))
    except (OSError, TypeError, ValueError):
        return False
