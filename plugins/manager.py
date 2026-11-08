from __future__ import annotations
import importlib
import logging
from pathlib import Path
from plugins.base import Plugin


class PluginManager:
    """Loads trusted Python plugin modules from ./plugins/extensions."""
    def __init__(self, app_context=None):
        self.app_context = app_context or {}
        self.plugins: list[Plugin] = []
        self.audio_processors = []

    def discover(self, directory=None):
        # путь от расположения файла, а не от текущей папки запуска
        path = Path(directory) if directory else Path(__file__).resolve().parent / "extensions"
        path.mkdir(parents=True, exist_ok=True)
        for file in path.glob("*.py"):
            if file.name.startswith("_"):
                continue
            module_name = f"plugins.extensions.{file.stem}"
            try:
                module = importlib.import_module(module_name)
                plugin_class = getattr(module, "PluginEntry", None)
                if plugin_class:
                    plugin = plugin_class()
                    plugin.on_load(self.app_context)
                    self.plugins.append(plugin)
                    if hasattr(plugin, "process"):
                        self.audio_processors.append(plugin)
            except Exception:
                logging.exception("Не удалось загрузить плагин %s", module_name)

    def unload(self):
        for plugin in reversed(self.plugins):
            try: plugin.on_unload()
            except Exception: logging.exception("Plugin unload failed: %s", plugin.name)
        self.plugins.clear()
        self.audio_processors.clear()
