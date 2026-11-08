from __future__ import annotations
import sys


def enable_dark_titlebar(widget) -> None:
    """Windows 10/11: тёмная системная шапка окна (иначе белая полоса ломает весь дизайн)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        value = ctypes.c_int(1)
        for attr in (20, 19):             # DWMWA_USE_IMMERSIVE_DARK_MODE (новый и старый номер)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass
