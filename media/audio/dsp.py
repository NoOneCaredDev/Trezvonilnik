from __future__ import annotations
import numpy as np
from media.audio.mixer import rms_db, SILENCE_DB


class NoiseSuppressor:
    """Спектральный шумодав (spectral gating) на numpy: окно 2N с шагом N, sin-окна, overlap-add.
    Оценка шума по каждой частоте — «минимальная статистика»: быстро падает вслед за тишиной,
    медленно растёт. Это не нейросеть (RNNoise) — стационарный шум (вентилятор, гул) давит хорошо,
    чужую речь и музыку на фоне — нет. Задержка +1 кадр (20 мс)."""

    BIAS = 1.9          # поправка: минимум сглаженного спектра ≈ половина среднего шума

    def __init__(self, frame_size=960, strength=0.6):
        self.n = frame_size
        self.strength = float(strength)
        k = np.arange(2 * frame_size)
        self.win = np.sin(np.pi * (k + 0.5) / (2 * frame_size)).astype(np.float32)
        self.prev_in = np.zeros(frame_size, dtype=np.float32)
        self.tail = np.zeros(frame_size, dtype=np.float32)
        self.noise: np.ndarray | None = None
        self.smooth: np.ndarray | None = None
        self.prev_gain: np.ndarray | None = None
        self.frames = 0

    def set_strength(self, strength: float):
        self.strength = min(1.0, max(0.0, float(strength)))

    def process(self, frame: np.ndarray) -> np.ndarray:
        x = np.asarray(frame, dtype=np.float32)
        buf = np.concatenate((self.prev_in, x)) * self.win
        self.prev_in = x.copy()
        spec = np.fft.rfft(buf)
        mag = np.abs(spec) + 1e-3
        # Минимальная статистика: следим за минимумом СГЛАЖЕННОГО спектра (сырой спектр шума скачет
        # по Рэлею, и минимум по нему занижает уровень шума в разы) и вводим поправку на смещение.
        if self.noise is None:
            self.smooth, self.noise = mag.copy(), mag.copy()
        else:
            self.smooth = 0.75 * self.smooth + 0.25 * mag
            falling = self.smooth < self.noise
            self.noise = np.where(falling, 0.5 * self.noise + 0.5 * self.smooth, self.noise * 1.003)
        over = 0.9 + 1.6 * self.strength
        floor = 10 ** (-(8 + 22 * self.strength) / 20)
        gain = np.clip(1.0 - over * self.BIAS * self.noise / mag, floor, 1.0)
        gain = np.convolve(gain, [0.25, 0.5, 0.25], mode="same")           # сглаживаем по частоте
        if self.prev_gain is not None:
            gain = np.maximum(gain, 0.55 * self.prev_gain)                  # и по времени (меньше «бульканья»)
        self.prev_gain = gain
        y = np.fft.irfft(spec * gain, 2 * self.n).astype(np.float32) * self.win
        out = self.tail + y[:self.n]
        self.tail = y[self.n:].copy()
        self.frames += 1
        return out


class NoiseGate:
    """Гейт с удержанием и плавным открытием/закрытием (без щелчков)."""

    def __init__(self, threshold_db=-48.0, hold_frames=10):
        self.threshold_db = threshold_db
        self.hold_frames = hold_frames
        self.hold = 0
        self.gain = 0.0
        self.is_open = False

    def process(self, x: np.ndarray, level_db: float | None = None) -> np.ndarray:
        level = rms_db(x) if level_db is None else level_db
        if level > self.threshold_db:
            self.hold = self.hold_frames
        elif self.hold > 0:
            self.hold -= 1
        self.is_open = self.hold > 0
        target = 1.0 if self.is_open else 0.0
        if target == self.gain:
            return x * target
        ramp = np.linspace(self.gain, target, len(x), dtype=np.float32)
        self.gain = target
        return x * ramp


class EchoSuppressor:
    """Упрощённое эхоподавление: пока из колонок идёт громкий звук, пропускаем микрофон только если он
    заметно громче, чем эхо могло бы быть. Это НЕ настоящий AEC (тот вычитает эхо адаптивным фильтром)
    — в наушниках не нужен, на колонках режет эхо, но мешает перебивать собеседника."""

    def __init__(self, far_threshold_db=-50.0, margin_db=-6.0):
        self.far_threshold_db = far_threshold_db
        self.margin_db = margin_db
        self.gain = 1.0

    def process(self, x: np.ndarray, near_db: float, far_db: float) -> np.ndarray:
        duck = far_db > self.far_threshold_db and near_db < far_db + self.margin_db
        target = 0.08 if duck else 1.0
        if target == self.gain:
            return x * target
        ramp = np.linspace(self.gain, target, len(x), dtype=np.float32)
        self.gain = target
        return x * ramp
