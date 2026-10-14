"""Tests for the immutable data contracts."""

from __future__ import annotations

import numpy as np
import pytest

from openbrightness.due.models import DisplayFrame, LuminanceMetrics, OutputInfo
from tests.conftest import make_frame, uniform


def test_output_info_label() -> None:
    info = OutputInfo("eDP-1", "BOE", "NE160QDM-NY1", 1920, 1200, 60.0, is_primary=True)
    assert info.label == "eDP-1 (BOE NE160QDM-NY1)"


def test_output_info_label_empty_make_model() -> None:
    info = OutputInfo("HDMI-A-1", "", "", 2560, 1440, 144.0)
    assert info.label == "HDMI-A-1"


def test_frame_rejects_shape_mismatch() -> None:
    with pytest.raises(ValueError, match="shape"):
        DisplayFrame(data=uniform(0, 10, 10), width=20, height=10)


def test_frame_rejects_wrong_dtype() -> None:
    data = np.zeros((10, 10, 3), dtype=np.float32)
    with pytest.raises(ValueError, match="uint8"):
        DisplayFrame(data=data, width=10, height=10)


def test_frame_rejects_non_contiguous() -> None:
    base = np.ascontiguousarray(uniform(0, 10, 20))
    view = base[:, ::2, :]
    with pytest.raises(ValueError, match="contiguous"):
        DisplayFrame(data=view, width=10, height=10)


def test_get_subsampled_returns_copy() -> None:
    frame = make_frame(uniform(0, 40, 40))
    sub = frame.get_subsampled(4)
    assert sub.shape == (10, 10, 3)
    assert sub.flags["C_CONTIGUOUS"]
    sub[0, 0, 0] = 255
    assert frame.data[0, 0, 0] == 0


def test_get_subsampled_stride_matches_view() -> None:
    frame = make_frame(uniform(7, 40, 40))
    np.testing.assert_array_equal(frame.get_subsampled(4), frame.data[::4, ::4, :])


def test_get_subsampled_step_validation() -> None:
    frame = make_frame(uniform(0, 8, 8))
    with pytest.raises(ValueError, match="step"):
        frame.get_subsampled(0)


def test_metrics_contrast_normalized() -> None:
    metrics = LuminanceMetrics(
        mean_luminance=127.5,
        median_luminance=127.5,
        p10_luminance=0.0,
        p90_luminance=255.0,
        dark_ratio=0.5,
        bright_ratio=0.5,
        rms_contrast=63.75,
        temporal_delta=None,
        histogram=np.ones(64, dtype=np.float32) / 64,
        capture_latency_ms=1.0,
        analysis_latency_ms=0.5,
        width=4,
        height=4,
        timestamp_monotonic_ns=0,
    )
    assert metrics.rms_contrast_normalized == pytest.approx(0.5)
    assert metrics.subsample_shape == (4, 4)
