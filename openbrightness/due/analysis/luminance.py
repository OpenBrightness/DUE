"""Vectorized BT.709 luminance analysis (PLAN_V1.md section 3)."""

from __future__ import annotations

import time

import numpy as np
from numpy.typing import NDArray

from openbrightness.due.models import (
    BRIGHT_THRESHOLD,
    DARK_THRESHOLD,
    HISTOGRAM_BINS,
    DisplayFrame,
    LuminanceMetrics,
)

_SUBSAMPLE_STEP = 4


def _luma(rgb: NDArray[np.uint8]) -> NDArray[np.float32]:
    """BT.709 luma: Y = 0.2126 R + 0.7152 G + 0.0722 B, float32 in 0–255."""
    y: NDArray[np.float32] = (
        rgb[..., 0].astype(np.float32) * 0.2126
        + rgb[..., 1].astype(np.float32) * 0.7152
        + rgb[..., 2].astype(np.float32) * 0.0722
    )
    return y


def frame_luma(
    frame: DisplayFrame, step: int = _SUBSAMPLE_STEP
) -> tuple[NDArray[np.float32], int, int]:
    """Luma of the strided subsample — one gather pass, no intermediate copy.

    The arithmetic in :func:`_luma` writes a compact output array, so the
    strided view is read once and nothing needs ``ascontiguousarray``.
    Returns ``(y, sub_width, sub_height)``.
    """
    view = frame.data[::step, ::step, :]
    y = _luma(view)
    return y, view.shape[1], view.shape[0]


def _percentiles(y: NDArray[np.float32]) -> tuple[float, float, float]:
    """P10/P50/P90 in one partition pass (np.percentile equivalent, linear interp)."""
    flat = y.reshape(-1)
    n = flat.size
    positions = np.array([0.1, 0.5, 0.9]) * (n - 1)
    lower = np.floor(positions).astype(np.intp)
    upper = np.ceil(positions).astype(np.intp)
    parts = np.partition(flat, np.unique(np.concatenate([lower, upper])))
    lo = parts[lower]
    hi = parts[upper]
    frac = (positions - lower).astype(np.float32)
    quantiles = lo + (hi - lo) * frac
    return float(quantiles[0]), float(quantiles[1]), float(quantiles[2])


def _histogram(y: NDArray[np.float32]) -> NDArray[np.float32]:
    """64-bin histogram over 0–255, normalized by pixel count to sum 1."""
    flat = y.reshape(-1)
    bins = np.clip((flat * (HISTOGRAM_BINS / 256.0)).astype(np.intp), 0, HISTOGRAM_BINS - 1)
    counts = np.bincount(bins, minlength=HISTOGRAM_BINS)
    return (counts / flat.size).astype(np.float32)


class LuminanceAnalyzer:
    """Computes :class:`LuminanceMetrics` for a :class:`DisplayFrame`.

    Analysis runs on a 4x strided subsample which gives a ~22x speedup over
    full resolution at < 0.08% mean-luminance error (PLAN_V1.md section 3).
    """

    def __init__(self, subsample_step: int = _SUBSAMPLE_STEP) -> None:
        if subsample_step < 1:
            raise ValueError(f"subsample_step must be >= 1, got {subsample_step}")
        self._step = subsample_step

    def analyze(
        self,
        frame: DisplayFrame,
        temporal_delta: float | None = None,
        luma: NDArray[np.float32] | None = None,
    ) -> LuminanceMetrics:
        """Analyze a frame; pass ``luma`` (from :func:`frame_luma`) to avoid
        recomputing it when a caller (e.g. the coordinator) already has it."""
        t0 = time.perf_counter_ns()
        if luma is None:
            y, sub_w, sub_h = frame_luma(frame, self._step)
        else:
            y = luma
            sub_h, sub_w = y.shape

        p10, p50, p90 = _percentiles(y)
        dark_ratio = float(np.count_nonzero(y < DARK_THRESHOLD) / y.size)
        bright_ratio = float(np.count_nonzero(y > BRIGHT_THRESHOLD) / y.size)
        rms_contrast = float(y.std())
        histogram = _histogram(y)
        analysis_ms = (time.perf_counter_ns() - t0) / 1e6

        capture_ms = 0.0
        if frame.pts_ns is not None:
            capture_ms = (frame.captured_monotonic_ns - frame.pts_ns) / 1e6

        return LuminanceMetrics(
            mean_luminance=float(y.mean()),
            median_luminance=p50,
            p10_luminance=p10,
            p90_luminance=p90,
            dark_ratio=dark_ratio,
            bright_ratio=bright_ratio,
            rms_contrast=rms_contrast,
            temporal_delta=temporal_delta,
            histogram=histogram,
            capture_latency_ms=max(capture_ms, 0.0),
            analysis_latency_ms=analysis_ms,
            width=sub_w,
            height=sub_h,
            timestamp_monotonic_ns=frame.captured_monotonic_ns,
        )
