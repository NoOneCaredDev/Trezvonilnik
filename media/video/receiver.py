from __future__ import annotations
import threading
import time

import cv2
import numpy as np
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage


class StreamReceiver(QObject):
    """Декодирует JPEG ТОЛЬКО той трансляции, которую вы сейчас смотрите, и только последний кадр:
    если декодер не успевает, старые кадры выбрасываются, а не копятся в очереди."""
    frame = Signal(QImage)

    def __init__(self):
        super().__init__()
        self.watch_id: int | None = None
        self.fps = 0.0
        self._latest: bytes | None = None
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._stop = threading.Event()
        self._times: list[float] = []
        self._thread = threading.Thread(target=self._run, name="video-decode", daemon=True)
        self._thread.start()

    def set_watch(self, uid: int | None):
        with self._lock:
            self.watch_id, self._latest = uid, None
        self._times.clear()
        self.fps = 0.0

    def push(self, uid: int, jpeg: bytes):
        if uid != self.watch_id:
            return
        with self._lock:
            self._latest = jpeg
        self._event.set()

    def _run(self):
        while not self._stop.is_set():
            if not self._event.wait(0.3):
                continue
            self._event.clear()
            with self._lock:
                data, self._latest = self._latest, None
            if not data:
                continue
            try:
                bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if bgr is None:
                    continue
                h, w = bgr.shape[:2]
                self.frame.emit(QImage(bgr.data, w, h, bgr.strides[0], QImage.Format_BGR888).copy())
            except Exception:
                continue
            now = time.monotonic()
            self._times = [t for t in self._times if now - t < 2.0] + [now]
            self.fps = len(self._times) / 2.0 if len(self._times) > 1 else 0.0

    def close(self):
        self._stop.set()
        self._event.set()
