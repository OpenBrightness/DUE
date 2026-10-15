"""Core immutable data contracts for the DUE pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

HISTOGRAM_BINS: int = 64
DARK_THRESHOLD: float = 51.0
BRIGHT_THRESHOLD: float = 204.0


@dataclass(frozen=True, slots=True)
class OutputInfo:
    """A physical display output as reported by the compositor."""

    connector: str
    make: str
    model: str
    width: int
    height: int
    refresh_rate: float
    is_primary: bool = False

    @property
    def label(self) -> str:
        name = f"{self.make} {self.model}".strip()
        return f"{self.connector} ({name})" if name else self.connector


@dataclass(frozen=True, slots=True)
class DisplayFrame:
    """A single captured RGB frame.

    ``data`` is C-contiguous ``(H, W, 3)`` uint8 RGB *owned by this frame*:
    capture backends must copy out of the capture buffer before releasing it
    (see PLAN.md section 5). Rowstride padding is normalized at copy time.
    """

    data: NDArray[np.uint8]
    width: int
    height: int
    pts_ns: int | None = None
    captured_monotonic_ns: int = 0

    def __post_init__(self) -> None:
        if self.data.shape != (self.height, self.width, 3):
            raise ValueError(
                f"frame data shape {self.data.shape} does not match "
                f"({self.height}, {self.width}, 3)"
            )
        if self.data.dtype != np.uint8:
            raise ValueError(f"frame data dtype {self.data.dtype} is not uint8")
        if not self.data.flags["C_CONTIGUOUS"]:
            raise ValueError("frame data must be C-contiguous")

    def get_subsampled(self, step: int = 4) -> NDArray[np.uint8]:
        """Return a contiguous copy of the ``step``-fold strided subsample.

        Deliberately a copy: a strided *view* would reference capture memory
        that backends unmap immediately after the callback returns.
        """
        if step < 1:
            raise ValueError(f"step must be >= 1, got {step}")
        return np.ascontiguousarray(self.data[::step, ::step, :])


@dataclass(frozen=True, slots=True)
class LuminanceMetrics:
    """Computed statistics for one analyzed frame."""

    mean_luminance: float
    median_luminance: float
    p10_luminance: float
    p90_luminance: float
    dark_ratio: float
    bright_ratio: float
    rms_contrast: float
    temporal_delta: float | None
    histogram: NDArray[np.float32]
    capture_latency_ms: float
    analysis_latency_ms: float
    width: int
    height: int
    timestamp_monotonic_ns: int

    @property
    def rms_contrast_normalized(self) -> float:
        """RMS contrast scaled to 0.0–1.0 for TUI display."""
        return self.rms_contrast / 127.5

    @property
    def subsample_shape(self) -> tuple[int, int]:
        return (self.height, self.width)
