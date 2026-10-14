"""Temporal frame-delta tracking (PLAN_V1.md section 4)."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from openbrightness.due.analysis.luminance import _luma
from openbrightness.due.models import DisplayFrame


class TemporalTracker:
    """Tracks mean absolute luma change between consecutive frames.

    The first frame after start/reset (or after a resolution change) yields
    ``None``. Resolution changes silently rebase: the new frame becomes the
    previous without producing a delta.
    """

    def __init__(self, subsample_step: int = 4) -> None:
        if subsample_step < 1:
            raise ValueError(f"subsample_step must be >= 1, got {subsample_step}")
        self._step = subsample_step
        self._prev_y: NDArray[np.float32] | None = None
        self._frame_count: int = 0
        self._delta_count: int = 0
        self._delta_sum: float = 0.0
        self._delta_min: float | None = None
        self._delta_max: float | None = None

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def delta_mean(self) -> float | None:
        return self._delta_sum / self._delta_count if self._delta_count else None

    @property
    def delta_min(self) -> float | None:
        return self._delta_min

    @property
    def delta_max(self) -> float | None:
        return self._delta_max

    def update(self, frame: DisplayFrame, luma: NDArray[np.float32] | None = None) -> float | None:
        """Feed one frame; return the 0.0–1.0 delta or ``None``.

        Pass ``luma`` (from :func:`~openbrightness.due.analysis.luminance.frame_luma`)
        to avoid recomputing it when the caller already has it.
        """
        y = luma if luma is not None else _luma(frame.get_subsampled(self._step))
        self._frame_count += 1

        if self._prev_y is None or self._prev_y.shape != y.shape:
            self._prev_y = y
            return None

        delta = float(np.abs(y - self._prev_y).mean() / 255.0)
        self._prev_y = y

        self._delta_count += 1
        self._delta_sum += delta
        self._delta_min = delta if self._delta_min is None else min(self._delta_min, delta)
        self._delta_max = delta if self._delta_max is None else max(self._delta_max, delta)
        return delta

    def reset(self) -> None:
        """Drop the previous frame and all accumulated history."""
        self._prev_y = None
        self._frame_count = 0
        self._delta_count = 0
        self._delta_sum = 0.0
        self._delta_min = None
        self._delta_max = None
