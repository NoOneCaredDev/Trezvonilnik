from __future__ import annotations
import collections
import threading
import time
import numpy as np

SILENCE_DB = -100.0


def rms_db(x: np.ndarray) -> float:
    if len(x) == 0:
        return SILENCE_DB
    f = np.asarray(x, dtype=np.float32)
    rms = float(np.sqrt(np.mean(f * f)))
    return max(SILENCE_DB, 20.0 * np.log10(rms / 32768.0 + 1e-9))


class Channel:
    """Очередь сэмплов с небольшим джиттер-буфером.

    Пока не накопилось prefill — молчим (иначе любая неровность сети = треск);
    если буфер опустел — снова копим. Если накопилось больше max_buffer — отбрасываем
    самое старое, чтобы задержка не росла."""

    def __init__(self, prefill: int, max_buffer: int):
        self.prefill, self.max_buffer = prefill, max_buffer
        self.buf: collections.deque[np.ndarray] = collections.deque()
        self.buffered = 0
        self.primed = False
        self.level_db = SILENCE_DB
        self.last_push = 0.0

    def push(self, samples: np.ndarray):
        self.buf.append(samples)
        self.buffered += len(samples)
        self.level_db = rms_db(samples)
        self.last_push = time.monotonic()
        while self.buffered > self.max_buffer and len(self.buf) > 1:
            self.buffered -= len(self.buf.popleft())

    def pull(self, n: int) -> np.ndarray | None:
        if not self.primed:
            if self.buffered < self.prefill:
                return None
            self.primed = True
        out = np.zeros(n, dtype=np.int16)
        filled = 0
        while filled < n and self.buf:
            head = self.buf[0]
            take = min(len(head), n - filled)
            out[filled:filled + take] = head[:take]
            if take == len(head):
                self.buf.popleft()
            else:
                self.buf[0] = head[take:]
            filled += take
        self.buffered -= filled
        if filled < n:
            self.primed = False
        return out


class AudioMixer:
    """Каналы: (uid, kind), kind ∈ voice | sfx | music | self.
    Громкость и локальный мьют — у каждого получателя свои; сеть о них не знает."""

    def __init__(self, sample_rate=48000, prefill_ms=40, max_ms=240):
        self.sample_rate = sample_rate
        self.prefill = sample_rate * prefill_ms // 1000
        self.max_buffer = sample_rate * max_ms // 1000
        self.channels: dict[tuple[int, str], Channel] = {}
        self.user_volume: dict[int, float] = {}
        self.muted: set[int] = set()            # заглушен голос
        self.sfx_muted: set[int] = set()        # заглушен саундпад
        self.master = 1.0
        self.sfx_volume = 0.8
        self.music_volume = 0.6
        self.out_level_db = SILENCE_DB          # что сейчас играет в колонках (для эхоподавления)
        self.lock = threading.RLock()

    # --- управление ---------------------------------------------------------
    def set_volume(self, user_id: int, percent: int):
        with self.lock:
            self.user_volume[user_id] = max(0, min(200, percent)) / 100.0

    def volume_of(self, user_id: int) -> int:
        return int(round(self.user_volume.get(user_id, 1.0) * 100))

    def set_muted(self, user_id: int, muted: bool):
        with self.lock:
            (self.muted.add if muted else self.muted.discard)(user_id)

    def set_sfx_muted(self, user_id: int, muted: bool):
        with self.lock:
            (self.sfx_muted.add if muted else self.sfx_muted.discard)(user_id)

    def forget(self, user_id: int):
        with self.lock:
            for key in [k for k in self.channels if k[0] == user_id]:
                self.channels.pop(key, None)

    # --- данные -------------------------------------------------------------
    def push(self, user_id: int, samples: np.ndarray, kind: str = "voice"):
        samples = np.asarray(samples, dtype=np.int16)
        with self.lock:
            ch = self.channels.get((user_id, kind))
            if ch is None:
                ch = self.channels[(user_id, kind)] = Channel(self.prefill, self.max_buffer)
            ch.push(samples.copy())

    def level_db(self, user_id: int, kind: str = "voice") -> float:
        ch = self.channels.get((user_id, kind))
        if ch is None or time.monotonic() - ch.last_push > 0.35:
            return SILENCE_DB
        return ch.level_db

    def _gain(self, uid: int, kind: str) -> float:
        if kind == "voice":
            return 0.0 if uid in self.muted else self.user_volume.get(uid, 1.0)
        if kind == "sfx":
            return 0.0 if uid in self.sfx_muted else self.sfx_volume
        if kind == "music":
            return self.music_volume
        return self.sfx_volume          # self: превью и мониторинг

    def mix(self, n: int) -> np.ndarray:
        acc = np.zeros(n, dtype=np.float32)
        now = time.monotonic()
        with self.lock:
            for key, ch in list(self.channels.items()):
                data = ch.pull(n)
                if data is None:
                    if ch.buffered == 0 and now - ch.last_push > 30:
                        self.channels.pop(key, None)       # давно молчит — убираем
                    continue
                gain = self._gain(*key)
                if gain:
                    acc += data.astype(np.float32) * gain
        acc *= self.master
        out = np.clip(acc, -32768, 32767).astype(np.int16)
        self.out_level_db = rms_db(out)
        return out
