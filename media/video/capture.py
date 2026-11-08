from __future__ import annotations
import sys
from dataclasses import dataclass, field

import numpy as np

try:
    import cv2
except Exception:               # pragma: no cover
    cv2 = None

OWN_TITLES = ("Трезвонильник",)


class SourceGone(Exception):
    """Окно, которое мы транслировали, закрыли."""


@dataclass
class CaptureSource:
    kind: str                    # monitor | window
    title: str
    monitor: dict | None = None  # для monitor: {left, top, width, height}
    window: object = field(default=None, repr=False)   # для window: объект PyGetWindow

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.title}"


def _mss_class():
    import mss
    return getattr(mss, "MSS", None) or mss.mss


def list_sources() -> list[CaptureSource]:
    sources: list[CaptureSource] = []
    try:
        with _mss_class()() as sct:
            for i, mon in enumerate(sct.monitors[1:], start=1):
                sources.append(CaptureSource("monitor", f"Экран {i} · {mon['width']}×{mon['height']}", dict(mon)))
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import pygetwindow as gw
            seen = set()
            for win in gw.getAllWindows():
                title = (win.title or "").strip()
                if (not title or title in seen or any(title.startswith(t) for t in OWN_TITLES)
                        or win.width < 120 or win.height < 80 or getattr(win, "isMinimized", False)):
                    continue
                seen.add(title)
                sources.append(CaptureSource("window", title, window=win))
        except Exception:
            pass
    return sources


class ScreenGrabber:
    """mss нельзя шарить между потоками — каждый поток создаёт свой граббер."""

    def __init__(self):
        self.sct = _mss_class()()

    def grab(self, source: CaptureSource) -> np.ndarray | None:
        if source.kind == "monitor":
            area = source.monitor
        else:
            win = source.window
            try:
                if getattr(win, "isMinimized", False):
                    return None                                  # свёрнуто — держим последнюю картинку
                area = {"left": int(win.left), "top": int(win.top), "width": int(win.width), "height": int(win.height)}
            except Exception as exc:
                raise SourceGone(str(exc)) from exc
            bounds = self.sct.monitors[0]
            left, top = max(area["left"], bounds["left"]), max(area["top"], bounds["top"])
            right = min(area["left"] + area["width"], bounds["left"] + bounds["width"])
            bottom = min(area["top"] + area["height"], bounds["top"] + bounds["height"])
            if right - left < 16 or bottom - top < 16:
                return None
            area = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        shot = np.asarray(self.sct.grab(area))
        return shot[:, :, :3].copy()                              # BGRA → BGR (без лишней конвертации cv2)

    def close(self):
        try:
            self.sct.close()
        except Exception:
            pass


def thumbnail(source: CaptureSource, width: int = 320) -> np.ndarray | None:
    try:
        grabber = ScreenGrabber()
        try:
            frame = grabber.grab(source)
        finally:
            grabber.close()
        if frame is None or cv2 is None:
            return frame
        h, w = frame.shape[:2]
        return cv2.resize(frame, (width, max(1, int(h * width / w))), interpolation=cv2.INTER_AREA)
    except Exception:
        return None
