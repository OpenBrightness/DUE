"""Synthetic-matrix tests for the LuminanceAnalyzer (PLAN_V1.md M1)."""

from __future__ import annotations

import numpy as np
import pytest

from openbrightness.due.analysis.luminance import LuminanceAnalyzer
from openbrightness.due.models import HISTOGRAM_BINS, DisplayFrame
from tests.conftest import gray_ramp, make_frame, uniform

ANALYZER = LuminanceAnalyzer()


def test_black_frame(black_frame: DisplayFrame) -> None:
    m = ANALYZER.analyze(black_frame)
    assert m.mean_luminance == pytest.approx(0.0, abs=1e-3)
    assert m.median_luminance == pytest.approx(0.0, abs=1e-3)
    assert m.p10_luminance == pytest.approx(0.0, abs=1e-3)
    assert m.p90_luminance == pytest.approx(0.0, abs=1e-3)
    assert m.dark_ratio == 1.0
    assert m.bright_ratio == 0.0
    assert m.rms_contrast == pytest.approx(0.0, abs=1e-3)
    assert float(m.histogram.sum()) == pytest.approx(1.0)


def test_white_frame(white_frame: DisplayFrame) -> None:
    m = ANALYZER.analyze(white_frame)
    assert m.mean_luminance == pytest.approx(255.0, abs=1e-3)
    assert m.bright_ratio == 1.0
    assert m.dark_ratio == 0.0
    assert m.rms_contrast == pytest.approx(0.0, abs=1e-3)


def test_mid_gray_frame(mid_gray_frame: DisplayFrame) -> None:
    m = ANALYZER.analyze(mid_gray_frame)
    assert m.mean_luminance == pytest.approx(128.0, abs=1e-3)
    assert m.median_luminance == pytest.approx(128.0, abs=1e-3)
    assert m.dark_ratio == 0.0
    assert m.bright_ratio == 0.0


def test_gradient_percentiles(gradient_frame: DisplayFrame) -> None:
    # 4x subsample of the ramp picks columns 0,4,...,252 -> values 0,4,...,252.
    m = ANALYZER.analyze(gradient_frame)
    assert m.p10_luminance == pytest.approx(24.4, abs=1.5)
    assert m.median_luminance == pytest.approx(126.0, abs=1.5)
    assert m.p90_luminance == pytest.approx(227.6, abs=1.5)
    assert m.mean_luminance == pytest.approx(126.0, abs=1.5)


def test_checker_bimodal_ratios(checker_frame: DisplayFrame) -> None:
    m = ANALYZER.analyze(checker_frame)
    assert m.dark_ratio == pytest.approx(0.5, abs=0.01)
    assert m.bright_ratio == pytest.approx(0.5, abs=0.01)
    assert m.mean_luminance == pytest.approx(127.5, abs=1.5)


def test_rms_contrast_on_gray_ramp() -> None:
    y = gray_ramp(256, 256)[..., 0].astype(np.float32)
    expected = float(y.std())
    m = ANALYZER.analyze(make_frame(gray_ramp(256, 256)))
    assert m.rms_contrast == pytest.approx(expected, rel=0.01)


def test_histogram_normalization(gradient_frame: DisplayFrame) -> None:
    m = ANALYZER.analyze(gradient_frame)
    assert m.histogram.shape == (HISTOGRAM_BINS,)
    assert m.histogram.dtype == np.float32
    assert float(m.histogram.sum()) == pytest.approx(1.0, abs=1e-5)
    assert np.all(m.histogram >= 0)


def test_subsampling_accuracy_uniform() -> None:
    frame = make_frame(uniform(77, 240, 320))
    m = ANALYZER.analyze(frame)
    assert m.mean_luminance == pytest.approx(77.0, abs=0.5)
    assert m.width == 80
    assert m.height == 60


def test_subsampling_accuracy_random() -> None:
    rng = np.random.default_rng(42)
    rgb = rng.integers(0, 256, size=(480, 640, 3), dtype=np.uint8)
    frame = make_frame(rgb)
    m = ANALYZER.analyze(frame)
    y_full = (
        rgb[..., 0].astype(np.float32) * 0.2126
        + rgb[..., 1].astype(np.float32) * 0.7152
        + rgb[..., 2].astype(np.float32) * 0.0722
    )
    assert m.mean_luminance == pytest.approx(float(y_full.mean()), abs=0.5)


def test_temporal_delta_passthrough(black_frame: DisplayFrame) -> None:
    m = ANALYZER.analyze(black_frame, temporal_delta=0.25)
    assert m.temporal_delta == 0.25
    m0 = ANALYZER.analyze(black_frame)
    assert m0.temporal_delta is None


def test_latency_fields(black_frame: DisplayFrame) -> None:
    m = ANALYZER.analyze(black_frame)
    assert m.analysis_latency_ms >= 0.0
    assert m.capture_latency_ms == 0.0
