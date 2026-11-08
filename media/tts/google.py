from __future__ import annotations

import io
import shutil
import subprocess

import numpy as np
from gtts import gTTS

MAX_TEXT = 3000
RATE = 48000
MAX_AUDIO_BYTES = 20_000_000


def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        path = shutil.which("ffmpeg")
        if path:
            return path
        raise RuntimeError("Не найден ffmpeg для декодирования аудио")


def synthesize(text: str) -> tuple[np.ndarray, dict]:
    """Google Translate TTS (gTTS), русский язык → PCM16 mono/48 kHz."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Введите текст для озвучки")
    if len(text) > MAX_TEXT:
        raise ValueError(f"Максимум {MAX_TEXT} символов за одну озвучку")

    try:
        tts = gTTS(text=text, lang="ru", slow=False, timeout=(10, 30))
        output = io.BytesIO()
        tts.write_to_fp(output)
        audio = output.getvalue()
    except Exception as exc:
        # gTTS/requests могут вернуть длинные и малопонятные сетевые исключения.
        detail = str(exc).strip().replace("\n", " ")[:240]
        raise RuntimeError(
            "Google TTS не смог получить озвучку. Проверь подключение к интернету "
            "и доступность Google Translate" + (f": {detail}" if detail else "")
        ) from exc

    if not audio or len(audio) > MAX_AUDIO_BYTES:
        raise RuntimeError("Google TTS вернул пустой или слишком большой аудиофайл")

    try:
        proc = subprocess.run(
            [_ffmpeg(), "-nostdin", "-v", "error", "-i", "pipe:0", "-f", "s16le",
             "-ar", str(RATE), "-ac", "1", "pipe:1"],
            input=audio, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Истекло время декодирования аудио") from exc

    if proc.returncode != 0 or not proc.stdout:
        detail = proc.stderr.decode("utf-8", "replace").strip()[:180]
        raise RuntimeError("Не удалось декодировать аудио" + (f": {detail}" if detail else ""))

    pcm = np.frombuffer(proc.stdout, dtype=np.int16).copy()
    return pcm, {"duration": len(pcm) / RATE, "provider": "Google TTS", "language": "ru"}
