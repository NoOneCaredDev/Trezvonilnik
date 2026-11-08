"""Пример плагина. Файлы, имя которых начинается с «_», не загружаются — уберите «_», чтобы включить."""
import numpy as np
from plugins.base import Plugin


class PluginEntry(Plugin):
    name = "example_gain"
    version = "1.0"

    def process(self, samples: np.ndarray, context: dict) -> np.ndarray:
        # Example effect: subtle gain. Replace or remove as desired.
        return np.clip(samples.astype(np.float32) * 1.0, -32768, 32767).astype(np.int16)
