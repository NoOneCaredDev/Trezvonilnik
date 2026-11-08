from __future__ import annotations
import numpy as np

CODEC_PCM = 0
CODEC_OPUS = 1

try:                                        # opuslib при импорте ищет libopus
    import opuslib as _opus
except Exception:                           # нет пакета или нет системной библиотеки
    _opus = None


def opus_available() -> bool:
    return _opus is not None


class VoiceEncoder:
    """Один кодер на один поток (голос / саундпад / музыка): у Opus есть внутреннее состояние.
    Первый байт полезной нагрузки — тип кодека, чтобы клиенты с Opus и без него не ломали друг друга."""

    def __init__(self, sample_rate=48000, frame_ms=20, application="voip", bitrate: int | None = None,
                 prefer_opus=True):
        self.sample_rate = sample_rate
        self.frame_size = sample_rate * frame_ms // 1000
        self._enc = None
        if prefer_opus and _opus is not None:
            try:
                app = _opus.APPLICATION_AUDIO if application == "audio" else _opus.APPLICATION_VOIP
                self._enc = _opus.Encoder(sample_rate, 1, app)
                if bitrate:
                    self._enc.bitrate = bitrate
            except Exception:
                self._enc = None

    @property
    def name(self) -> str:
        return "opus" if self._enc else "pcm16"

    def encode(self, pcm: np.ndarray) -> bytes:
        pcm = np.asarray(pcm, dtype=np.int16).reshape(-1)
        if self._enc:
            return bytes((CODEC_OPUS,)) + self._enc.encode(pcm.tobytes(), self.frame_size)
        return bytes((CODEC_PCM,)) + pcm.tobytes()


class VoiceDecoder:
    def __init__(self, sample_rate=48000, frame_ms=20):
        self.frame_size = sample_rate * frame_ms // 1000
        self._dec = None
        if _opus is not None:
            try:
                self._dec = _opus.Decoder(sample_rate, 1)
            except Exception:
                self._dec = None

    def decode(self, payload: bytes) -> np.ndarray | None:
        """None — если кадр невозможно декодировать (например, пришёл Opus, а libopus нет)."""
        if len(payload) < 2:
            return None
        tag, body = payload[0], payload[1:]
        if tag == CODEC_PCM:
            if len(body) % 2:
                return None
            return np.frombuffer(body, dtype=np.int16).copy()
        if tag == CODEC_OPUS and self._dec is not None:
            raw = self._dec.decode(body, self.frame_size)
            return np.frombuffer(raw, dtype=np.int16).copy()
        return None
