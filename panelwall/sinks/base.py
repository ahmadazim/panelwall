from __future__ import annotations

import numpy as np


class Sink:
    """Something that displays a frame. Exactly one method matters."""

    def show(self, frame: np.ndarray) -> None:  # (H, W, 3) uint8 RGB
        raise NotImplementedError

    def set_brightness(self, level: int) -> None:  # 0..255
        pass

    def close(self) -> None:
        pass
