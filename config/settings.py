from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path

from app.paths import data_dir

# Пресеты демонстрации: (ширина, fps, целевой битрейт кбит/с)
STREAM_PRESETS = {
    "low":      {"title": "Экономный · 640p · 10 fps",   "width": 640,  "fps": 10, "kbps": 900},
    "balanced": {"title": "Обычный · 960p · 15 fps",     "width": 960,  "fps": 15, "kbps": 2500},
    "high":     {"title": "Чёткий · 1280p · 20 fps",     "width": 1280, "fps": 20, "kbps": 5000},
    "ultra":    {"title": "Максимум · 1600p · 30 fps",   "width": 1600, "fps": 30, "kbps": 9000},
}

DEFAULT_WHEEL = [
    {"name": "Да", "weight": 1.0},
    {"name": "Нет", "weight": 1.0},
    {"name": "Спроси потом", "weight": 0.5},
]


@dataclass
class AppSettings:
    # профиль
    nickname: str = "Пользователь"
    last_mode: str = "host"          # host | join
    last_host_ip: str = ""
    room_name: str = "ИСТИННЫЕ НАТУРАЛЫ"
    avatar_source: str = ""          # путь к исходнику своей аватарки
    local_avatars: dict = field(default_factory=dict)   # ник -> файл (видно только мне)
    # сеть
    network_port: int = 5000
    # аудио
    mic_index: int | None = None
    output_index: int | None = None
    sample_rate: int = 48000         # зафиксировано: весь конвейер 48 кГц
    block_ms: int = 20
    mic_gain: int = 100              # %
    gate_enabled: bool = True
    gate_threshold_db: float = -48.0
    noise_suppression: bool = True
    ns_strength: int = 60            # 0..100
    echo_suppression: bool = False
    output_volume: int = 100
    sfx_volume: int = 80
    music_volume: int = 60
    voice_effect: str = "none"
    voice_intensity: int = 50
    # демонстрация
    stream_preset: str = "balanced"
    video_fps: int = 15
    video_width: int = 960
    video_kbps: int = 2500
    # интерфейс
    animations: bool = True
    toasts: bool = True
    reactions: bool = True
    wheel_options: list = field(default_factory=lambda: [dict(o) for o in DEFAULT_WHEEL])
    # устаревшее поле, оставлено ради совместимости со старым config.ini
    video_jpeg_quality: int = 65
    codec: str = "opus"

    def apply_preset(self, name: str) -> None:
        preset = STREAM_PRESETS.get(name)
        if preset:
            self.stream_preset = name
            self.video_width, self.video_fps, self.video_kbps = preset["width"], preset["fps"], preset["kbps"]


class SettingsStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else data_dir() / "settings.json"

    def load(self) -> AppSettings:
        settings = AppSettings()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return settings
        except Exception:
            logging.exception("Не удалось прочитать настройки, использую значения по умолчанию")
            return settings
        known = {f.name for f in fields(AppSettings)}
        for key, value in raw.items():
            if key in known:
                setattr(settings, key, value)
        return settings

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
