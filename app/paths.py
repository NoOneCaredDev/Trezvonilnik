"""Где приложение хранит свои данные (звуки, аватарки, настройки).

Раньше звуки лежали во Temp — оттуда их в любой момент чистит система.
Теперь всё живёт в %APPDATA%/Trezvonilnik (или в TREZVONILNIK_HOME, если задана).
"""
from __future__ import annotations
import os
import sys
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("TREZVONILNIK_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Trezvonilnik"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Trezvonilnik"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "trezvonilnik"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _sub(name: str) -> Path:
    path = data_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def sounds_dir() -> Path:
    return _sub("sounds")


def avatars_dir() -> Path:
    return _sub("avatars")
