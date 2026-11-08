from __future__ import annotations
import numpy as np


class AudioProcessorChain:
    def __init__(self, processors=None):
        self.processors = list(processors or [])

    def process(self, samples: np.ndarray, context: dict) -> np.ndarray:
        result = samples
        for processor in self.processors:
            result = processor.process(result, context)
        return np.asarray(result, dtype=np.int16)
