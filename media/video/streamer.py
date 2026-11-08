from __future__ import annotations
import threading
import time

import cv2

from media.video.capture import CaptureSource, ScreenGrabber, SourceGone


class VideoStreamer:
    """Захват → JPEG → фрагменты в сеть.

    Экономим трафик и CPU: пока никто не смотрит (viewers == 0 и нет self-view), кадры не кодируются
    и не отправляются — сервер всё равно не стал бы их пересылать.
    Качество JPEG подстраивается под целевой битрейт пресета: кадр не должен превышать kbps/8/fps байт."""

    MIN_Q, MAX_Q = 28, 88

    def __init__(self, send_frame, source: CaptureSource, fps=15, width=960, kbps=2500,
                 on_local_frame=None, on_ended=None, grabber_factory=ScreenGrabber):
        self.send_frame = send_frame
        self.source = source
        self.fps, self.width, self.kbps = max(1, fps), width, kbps
        self.on_local_frame = on_local_frame
        self.on_ended = on_ended
        self.grabber_factory = grabber_factory
        self.viewers = 0
        self.self_view = False
        self.quality = 70
        self.last_frame_bytes = 0
        self.frames_sent = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def max_frame_bytes(self) -> int:
        return int(self.kbps * 1000 / 8 / self.fps)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="screen-capture", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.5)

    def _encode(self, frame) -> bytes:
        limit = self.max_frame_bytes
        for _ in range(4):
            ok, enc = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, int(self.quality)])
            if not ok:
                return b""
            if len(enc) <= limit or self.quality <= self.MIN_Q:
                break
            self.quality = max(self.MIN_Q, self.quality - 7)
        if len(enc) < limit * 0.6 and self.quality < self.MAX_Q:
            self.quality += 2                       # запас по битрейту — поднимаем качество плавно
        return enc.tobytes()

    def _run(self):
        try:
            grabber = self.grabber_factory()
        except Exception as exc:
            if self.on_ended:
                self.on_ended(f"не удалось начать захват: {exc}")
            return
        interval = 1.0 / self.fps
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                want_net, want_local = self.viewers > 0, self.self_view and self.on_local_frame
                if not (want_net or want_local):
                    self._stop.wait(0.15)
                    continue
                try:
                    frame = grabber.grab(self.source)
                except SourceGone:
                    if self.on_ended:
                        self.on_ended("окно закрыто")
                    return
                if frame is None:
                    self._stop.wait(0.2)
                    continue
                h, w = frame.shape[:2]
                if w > self.width:
                    frame = cv2.resize(frame, (self.width, max(1, int(h * self.width / w))), interpolation=cv2.INTER_AREA)
                if want_local:
                    self.on_local_frame(frame)
                if want_net:
                    data = self._encode(frame)
                    if data:
                        self.last_frame_bytes = len(data)
                        self.send_frame(data)
                        self.frames_sent += 1
                self._stop.wait(max(0.0, interval - (time.monotonic() - started)))
        except Exception as exc:
            if self.on_ended:
                self.on_ended(f"ошибка захвата: {exc}")
        finally:
            try:
                grabber.close()
            except Exception:
                pass
