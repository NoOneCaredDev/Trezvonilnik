from __future__ import annotations
from typing import Protocol
import numpy as np


class AudioProcessor(Protocol):
    name: str
    def process(self, samples: np.ndarray, context: dict) -> np.ndarray: ...


class Plugin:
    name = "unnamed"
    version = "0.1"
    def on_load(self, app_context: dict) -> None: pass
    def on_unload(self) -> None: pass
