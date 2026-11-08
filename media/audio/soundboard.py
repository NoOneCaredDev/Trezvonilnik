from __future__ import annotations
import json
import logging
import shutil
import subprocess
import threading
import time
import uuid
import wave
from dataclasses import dataclass, asdict, fields
from pathlib import Path

import numpy as np

from app.paths import sounds_dir
from media.audio.codec import VoiceEncoder

RATE = 48000
FRAME = 960
MAX_SECONDS = 20
MAX_SOUNDS = 80


def _ffmpeg() -> str | None:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def decode_audio_file(path: str, rate: int = RATE, max_seconds: float = MAX_SECONDS) -> tuple[np.ndarray, bool]:
    """Любой звук → моно int16 48 кГц. Возвращает (данные, обрезано_ли)."""
    data = None
    try:
        import soundfile as sf
        audio, src_rate = sf.read(path, dtype="float32", always_2d=True)
        mono = audio.mean(axis=1)
        if src_rate != rate and len(mono):
            n = int(len(mono) * rate / src_rate)
            mono = np.interp(np.linspace(0, len(mono) - 1, n), np.arange(len(mono)), mono)
        data = (np.clip(mono, -1, 1) * 32767).astype(np.int16)
    except Exception:
        ff = _ffmpeg()
        if not ff:
            raise ValueError("Не удалось прочитать файл (нужен ffmpeg для этого формата)")
        proc = subprocess.run([ff, "-v", "error", "-i", path, "-t", str(max_seconds + 1), "-f", "s16le",
                               "-ar", str(rate), "-ac", "1", "pipe:1"], capture_output=True, timeout=60)
        if proc.returncode != 0 or not proc.stdout:
            raise ValueError("Не удалось декодировать файл")
        data = np.frombuffer(proc.stdout, dtype=np.int16).copy()
    limit = int(rate * max_seconds)
    truncated = len(data) > limit
    return data[:limit], truncated


@dataclass
class Sound:
    id: str
    name: str
    emoji: str = "🔊"
    volume: int = 100
    pinned: bool = False


class SoundLibrary:
    """Звуки хранятся в AppData/Trezvonilnik/sounds как нормализованные WAV + library.json."""

    def __init__(self, directory: str | Path | None = None):
        self.dir = Path(directory) if directory else sounds_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest = self.dir / "library.json"
        self.sounds: list[Sound] = []
        self._cache: dict[str, np.ndarray] = {}
        self.load()

    def load(self):
        try:
            raw = json.loads(self.manifest.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raw = []
        except Exception:
            logging.exception("library.json повреждён")
            raw = []
        known = {f.name for f in fields(Sound)}
        self.sounds = [Sound(**{k: v for k, v in item.items() if k in known}) for item in raw
                       if (self.dir / f"{item.get('id')}.wav").exists()]

    def save(self):
        tmp = self.manifest.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(s) for s in self.sounds], ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.manifest)

    def get(self, sound_id: str) -> Sound | None:
        return next((s for s in self.sounds if s.id == sound_id), None)

    def add(self, source_path: str, name: str, emoji: str = "🔊", volume: int = 100) -> tuple[Sound, bool]:
        if len(self.sounds) >= MAX_SOUNDS:
            raise ValueError(f"Максимум {MAX_SOUNDS} звуков")
        pcm, truncated = decode_audio_file(source_path)
        if len(pcm) < RATE // 20:
            raise ValueError("Звук слишком короткий")
        sound = Sound(uuid.uuid4().hex[:10], name.strip() or Path(source_path).stem, emoji or "🔊", volume,
                      pinned=sum(s.pinned for s in self.sounds) < 4)
        with wave.open(str(self.dir / f"{sound.id}.wav"), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(RATE)
            wf.writeframes(pcm.tobytes())
        self._cache[sound.id] = pcm
        self.sounds.append(sound)
        self.save()
        return sound, truncated

    def update(self, sound_id: str, **changes):
        sound = self.get(sound_id)
        if sound:
            for k, v in changes.items():
                if hasattr(sound, k):
                    setattr(sound, k, v)
            self.save()

    def remove(self, sound_id: str):
        self.sounds = [s for s in self.sounds if s.id != sound_id]
        self._cache.pop(sound_id, None)
        try:
            (self.dir / f"{sound_id}.wav").unlink()
        except OSError:
            pass
        self.save()

    def pcm(self, sound_id: str) -> np.ndarray | None:
        if sound_id not in self._cache:
            try:
                with wave.open(str(self.dir / f"{sound_id}.wav"), "rb") as wf:
                    self._cache[sound_id] = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).copy()
            except Exception:
                return None
        return self._cache[sound_id]


class SoundPlayer:
    """Проигрывает звук «вживую»: по кадру в 20 мс — в сеть (отдельным типом пакетов SFX,
    поэтому хост может его запретить, а получатель — заглушить локально) и себе в микшер."""

    def __init__(self, send_frame, push_local, on_finished=None):
        self.send_frame = send_frame
        self.push_local = push_local
        self.on_finished = on_finished
        self.encoder = VoiceEncoder(RATE, 20, "audio", bitrate=64_000)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.current: str | None = None

    @property
    def playing(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def play(self, sound_id: str, pcm: np.ndarray, volume: float = 1.0, broadcast: bool = True):
        self.stop()
        self._stop = stop = threading.Event()
        self.current = sound_id
        data = (pcm.astype(np.float32) * volume).clip(-32768, 32767).astype(np.int16)
        pad = (-len(data)) % FRAME
        data = np.pad(data, (0, pad))

        def run():
            t = time.monotonic()
            for i in range(0, len(data), FRAME):
                if stop.is_set():
                    break
                frame = data[i:i + FRAME]
                self.push_local(frame)
                if broadcast:
                    try:
                        self.send_frame(self.encoder.encode(frame))
                    except Exception:
                        pass
                t += FRAME / RATE
                # первые кадры отдаём сразу — джиттер-буфер получателя быстро наполняется
                delay = t - time.monotonic() - (0.06 if i < FRAME * 3 else 0)
                if delay > 0:
                    stop.wait(delay)
            if self.current == sound_id:
                self.current = None
            if self.on_finished:
                self.on_finished(sound_id)

        self._thread = threading.Thread(target=run, name="soundpad", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=0.5)
        self.current = None
