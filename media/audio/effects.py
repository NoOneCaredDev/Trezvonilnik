"""Войсченджер: эффекты как обычные AudioProcessor — встают в ту же цепочку, что и плагины."""
from __future__ import annotations
import numpy as np

EFFECTS = {
    "none":     "Без эффекта",
    "chipmunk": "Бурундук",
    "deep":     "Бас",
    "robot":    "Робот",
    "alien":    "Пришелец",
    "demon":    "Демон",
    "echo":     "Эхо",
    "radio":    "Рация",
}


class PitchShifter:
    """Потоковый питч-шифтер на двух плавающих линиях задержки с кроссфейдом
    (классика «вращающихся головок»). Работает блоками любой длины, формант не сохраняет —
    для шуточного голоса это даже плюс."""

    def __init__(self, semitones: float, window=2048):
        self.ratio = 2.0 ** (semitones / 12.0)
        self.w = window
        self.hist = np.zeros(window + 4, dtype=np.float32)
        self.phase = 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        buf = np.concatenate((self.hist, x.astype(np.float32)))
        base = len(self.hist)
        t = np.arange(n, dtype=np.float32)
        rate = 1.0 - self.ratio                     # на сколько меняется задержка за сэмпл
        d1 = np.mod(self.phase + rate * t, self.w)
        d2 = np.mod(d1 + self.w / 2, self.w)
        out = np.zeros(n, dtype=np.float32)
        for d in (d1, d2):
            pos = base + t - d
            i0 = np.floor(pos).astype(np.int64)
            frac = (pos - i0).astype(np.float32)
            sample = buf[i0] * (1 - frac) + buf[i0 + 1] * frac
            gain = 1.0 - np.abs(2.0 * d / self.w - 1.0)      # треугольное окно, g(d1)+g(d2)=1
            out += sample * gain
        self.phase = float(np.mod(self.phase + rate * n, self.w))
        self.hist = buf[-len(self.hist):]
        return out


class RingMod:
    def __init__(self, freq: float, mix: float, sample_rate=48000):
        self.freq, self.mix, self.sr, self.phase = freq, mix, sample_rate, 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        t = (np.arange(n) + self.phase) / self.sr
        self.phase = (self.phase + n) % self.sr
        carrier = np.sin(2 * np.pi * self.freq * t).astype(np.float32)
        return x * (1 - self.mix) + x * carrier * self.mix


class Echo:
    def __init__(self, delay_ms=260, feedback=0.4, mix=0.45, sample_rate=48000):
        self.d = int(sample_rate * delay_ms / 1000)
        self.fb, self.mix = feedback, mix
        self.line = np.zeros(self.d, dtype=np.float32)

    def process(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        out = np.empty(n, dtype=np.float32)
        # задержка (260 мс) намного больше блока (20 мс) → блок целиком зависит от прошлого
        wet = self.line[:n] if n <= self.d else np.pad(self.line, (0, n - self.d))
        out[:] = x + wet * self.mix
        self.line = np.concatenate((self.line[n:], x + wet * self.fb))[-self.d:] if n < self.d \
            else (x + wet * self.fb)[-self.d:]
        return out


class Biquad:
    def __init__(self, b, a):
        self.b, self.a = b, a
        self.z1 = self.z2 = 0.0

    @classmethod
    def bandpass(cls, f0, q, sr=48000):
        w0 = 2 * np.pi * f0 / sr
        alpha = np.sin(w0) / (2 * q)
        b0, b1, b2 = alpha, 0.0, -alpha
        a0, a1, a2 = 1 + alpha, -2 * np.cos(w0), 1 - alpha
        return cls((b0 / a0, b1 / a0, b2 / a0), (a1 / a0, a2 / a0))

    def process(self, x: np.ndarray) -> np.ndarray:
        b0, b1, b2 = self.b
        a1, a2 = self.a
        z1, z2 = self.z1, self.z2
        out = np.empty(len(x), dtype=np.float32)
        for i, v in enumerate(x.tolist()):
            y = b0 * v + z1
            z1 = b1 * v - a1 * y + z2
            z2 = b2 * v - a2 * y
            out[i] = y
        self.z1, self.z2 = z1, z2
        return out


def _soft_clip(x: np.ndarray, drive: float) -> np.ndarray:
    return np.tanh(x / 32768.0 * drive) * 32768.0 / np.tanh(drive)


class VoiceChanger:
    """Ставится в AudioProcessorChain. set_effect() можно вызывать из GUI-потока в любой момент."""
    name = "voice_changer"

    def __init__(self, effect="none", intensity=50, sample_rate=48000):
        self.sr = sample_rate
        self.effect, self.intensity = "none", 50
        self._chain: list = []
        self.set_effect(effect, intensity)

    def set_effect(self, effect: str, intensity: int = 50):
        k = max(0.0, min(2.0, intensity / 50.0))          # 50 % — «как задумано»
        sr = self.sr
        chain: list = []
        if effect == "chipmunk":
            chain = [PitchShifter(+5 * k + 2)]
        elif effect == "deep":
            chain = [PitchShifter(-(3 * k + 2))]
        elif effect == "robot":
            chain = [RingMod(55 + 20 * k, 0.9, sr)]
        elif effect == "alien":
            chain = [PitchShifter(+3 * k), RingMod(9 + 6 * k, 0.55, sr)]
        elif effect == "demon":
            chain = [PitchShifter(-(5 * k + 2)), "clip"]
        elif effect == "echo":
            chain = [Echo(180 + 120 * k, 0.35 + 0.15 * k, 0.5, sr)]
        elif effect == "radio":
            chain = [Biquad.bandpass(1500, 0.9, sr), "clip"]
        else:
            effect = "none"
        self.effect, self.intensity = effect, intensity
        self._chain = chain

    def process(self, samples: np.ndarray, context: dict | None = None) -> np.ndarray:
        chain = self._chain
        if not chain:
            return samples
        x = samples.astype(np.float32)
        for stage in chain:
            x = _soft_clip(x, 3.0) if stage == "clip" else stage.process(x)
        return np.clip(x, -32768, 32767).astype(np.int16)
