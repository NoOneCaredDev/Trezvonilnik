from __future__ import annotations
import hashlib
import io
from pathlib import Path

from PIL import Image, ImageSequence

from app.paths import avatars_dir

MAX_BYTES = 90_000       # столько можно слать по UDP-кускам; сервер режет всё, что больше 120 КБ
MAX_FRAMES = 48
MAX_SECONDS = 6.0


def avatar_hash(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:12]


def _square(img: Image.Image, size: int) -> Image.Image:
    img = img.convert("RGBA")
    side = min(img.size)
    left, top = (img.width - side) // 2, (img.height - side) // 2
    return img.crop((left, top, left + side, top + side)).resize((size, size), Image.LANCZOS)


def process_avatar(path: str, max_bytes: int = MAX_BYTES) -> tuple[bytes, bool]:
    """Любая картинка/гифка → квадратный WebP (анимированный, если исходник анимирован),
    ужатый до max_bytes подбором размера и качества. Возвращает (байты, анимирован_ли)."""
    with Image.open(path) as img:
        animated = getattr(img, "n_frames", 1) > 1
        frames, durations = [], []
        if animated:
            total = 0
            for frame in ImageSequence.Iterator(img):
                dur = max(20, int(frame.info.get("duration", 80)))
                if total + dur > MAX_SECONDS * 1000 or len(frames) >= MAX_FRAMES:
                    break
                frames.append(frame.copy())
                durations.append(dur)
                total += dur
        else:
            frames = [img.copy()]
    last = b""
    for size in (160, 128, 96, 72, 56):
        for quality in (82, 65, 45, 30):
            squares = [_square(f, size) for f in frames]
            buf = io.BytesIO()
            if animated and len(squares) > 1:
                squares[0].save(buf, "WEBP", save_all=True, append_images=squares[1:], duration=durations,
                                loop=0, quality=quality, method=3)
            else:
                squares[0].save(buf, "WEBP", quality=quality, method=4)
            last = buf.getvalue()
            if len(last) <= max_bytes:
                return last, animated and len(squares) > 1
    # самый жёсткий вариант: статичный первый кадр
    buf = io.BytesIO()
    _square(frames[0], 64).save(buf, "WEBP", quality=40)
    return buf.getvalue(), False


class AvatarStore:
    """Кэш аватарок по хэшу содержимого: перезаход в комнату не требует новой загрузки."""

    def __init__(self, directory: str | Path | None = None):
        self.dir = Path(directory) if directory else avatars_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.mem: dict[str, bytes] = {}

    def put(self, data: bytes) -> str:
        digest = avatar_hash(data)
        self.mem[digest] = data
        target = self.dir / f"{digest}.webp"
        if not target.exists():
            target.write_bytes(data)
        return digest

    def get(self, digest: str) -> bytes | None:
        if not digest:
            return None
        if digest in self.mem:
            return self.mem[digest]
        target = self.dir / f"{digest}.webp"
        if target.exists():
            self.mem[digest] = target.read_bytes()
            return self.mem[digest]
        return None
