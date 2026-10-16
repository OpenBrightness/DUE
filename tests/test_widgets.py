"""Pure-render tests for the redesigned widgets (G4–G12)."""

from __future__ import annotations

import numpy as np
import pytest

from openbrightness.due.models import LuminanceMetrics
from openbrightness.due.tui.widgets.histogram import (
    _group_bins,
    _render_axis,
    _render_multi_line_bars,
    _render_percentile_markers,
    _render_y_axis,
)
from openbrightness.due.tui.widgets.metric_card import (
    MOTION_LIGHT_MAX,
    MOTION_STATIC_MAX,
    _render_bar,
    _render_composition_bar,
    motion_tag,
)


def make_metrics(
    hist: np.ndarray | None = None,
    p10: float = 40.0,
    p50: float = 128.0,
    p90: float = 220.0,
    delta: float | None = 0.01,
    dark: float = 0.1,
    bright: float = 0.2,
) -> LuminanceMetrics:
    if hist is None:
        hist = np.zeros(64, dtype=np.float32)
        hist[32] = 1.0
    return LuminanceMetrics(
        mean_luminance=128.0,
        median_luminance=p50,
        p10_luminance=p10,
        p90_luminance=p90,
        dark_ratio=dark,
        bright_ratio=bright,
        rms_contrast=55.5,
        temporal_delta=delta,
        histogram=hist,
        capture_latency_ms=1.0,
        analysis_latency_ms=0.5,
        width=480,
        height=300,
        timestamp_monotonic_ns=0,
    )


# --- histogram (G4, G5, G9) -------------------------------------------------


def test_multi_line_bars_dimensions() -> None:
    rows = _render_multi_line_bars(make_metrics(), rows=6, width=64)
    assert len(rows) == 6
    assert all(len(r) == 64 for r in rows)


def test_multi_line_bars_zero_histogram() -> None:
    rows = _render_multi_line_bars(make_metrics(hist=np.zeros(64, dtype=np.float32)))
    assert rows == ["(waiting for frames)"]


def test_multi_line_bars_spike_reaches_top() -> None:
    hist = np.zeros(64, dtype=np.float32)
    hist[10] = 1.0
    rows = _render_multi_line_bars(make_metrics(hist=hist), rows=6, width=64)
    assert rows[0][10] == "█"
    assert rows[-1][10] == "█"
    assert rows[0][11] == " "


def test_group_bins_reduces_to_width() -> None:
    hist = np.linspace(0, 1, 64, dtype=np.float32)
    grouped = _group_bins(hist, width=32)
    assert grouped.size == 32
    assert float(grouped.sum()) == pytest.approx(float(hist.sum()), rel=1e-5)


def test_group_bins_wide_width_keeps_all() -> None:
    hist = np.ones(64, dtype=np.float32)
    assert _group_bins(hist, width=64).size == 64
    assert _group_bins(hist, width=None).size == 64


def test_group_bins_floor_applies() -> None:
    hist = np.ones(64, dtype=np.float32)
    grouped = _group_bins(hist, width=4)  # floor of 16
    assert grouped.size >= 16


def test_multi_line_bars_width_grouping() -> None:
    rows = _render_multi_line_bars(make_metrics(), rows=6, width=32)
    assert all(len(r) == 32 for r in rows)


def test_y_axis_labels() -> None:
    bars = ["xxxx"] * 6
    axis = _render_y_axis(bars, 6)
    assert axis[0].startswith("100% │")
    assert axis[-1].startswith("  0% └")
    assert any(line.startswith(" 50% │") for line in axis)
    assert all(len(line) == len("100% │") + 4 for line in axis)


def test_axis_threshold_ticks() -> None:
    ruler, labels = _render_axis(64)
    assert len(ruler) == 64 and len(labels) == 64
    assert "Dark 51" in labels
    assert "Bright 204" in labels
    assert ruler.count("┴") == 5


def test_axis_labels_fit_at_min_width() -> None:
    ruler, labels = _render_axis(16)
    assert len(ruler) == 16 and len(labels) == 16
    assert "Dark 51" in labels  # early labels win, later truncate at edge


def test_percentile_markers_placed() -> None:
    carets, labels = _render_percentile_markers(make_metrics(), 64)
    assert carets.count("▲") == 3
    assert "P10" in labels and "P50" in labels and "P90" in labels


def test_percentile_markers_merge_on_collision() -> None:
    # cluster close enough to merge labels, far enough for distinct caret columns
    m = make_metrics(p10=120.0, p50=128.0, p90=136.0)
    carets, labels = _render_percentile_markers(m, 64)
    assert carets.count("▲") == 3
    assert "P10/P50/P90" in labels


def test_percentile_markers_edge_clamp() -> None:
    m = make_metrics(p10=0.0, p50=0.0, p90=255.0)
    carets, labels = _render_percentile_markers(m, 32)
    assert len(carets) == 32 and len(labels) == 32
    assert carets[0] == "▲"
    assert carets[-1] == "▲"


# --- metric card pieces (G6, G12) -------------------------------------------


def test_composition_bar_sums_to_width() -> None:
    for dark, bright in ((0.0, 0.0), (0.5, 0.5), (1.0, 0.0), (0.33, 0.33), (0.005, 0.005)):
        bar = _render_composition_bar(dark, bright, width=24)
        blocks = "".join(ch for ch in bar if ch in "█░▒")
        assert len(blocks) == 24, (dark, bright, len(blocks))


def test_composition_bar_segments_reflect_ratios() -> None:
    bar = _render_composition_bar(0.5, 0.25, width=24)
    assert "█" * 12 in bar
    assert "▒" * 6 in bar


def test_render_bar_bounds() -> None:
    assert _render_bar(0.0, width=10) == "[░░░░░░░░░░]"
    assert _render_bar(255.0, width=10) == "[██████████]"


def test_motion_tag_boundaries() -> None:
    assert motion_tag(None) == "—"
    assert motion_tag(0.0) == "Static"
    assert motion_tag(MOTION_STATIC_MAX) == "Static"
    assert motion_tag(MOTION_STATIC_MAX + 1e-9) == "Light motion"
    assert motion_tag(MOTION_LIGHT_MAX) == "Light motion"
    assert motion_tag(MOTION_LIGHT_MAX + 1e-9) == "Active motion"


# --- trend window (G7) -------------------------------------------------------


def test_trend_window_truncates_and_clears() -> None:
    from openbrightness.due.tui.widgets.trend import TrendWidget

    w = TrendWidget()
    for i in range(40):
        w._luma.append(float(i))
        w._delta.append(float(i) / 100.0)
    assert len(w._luma) == 30
    assert next(iter(w._luma)) == 10.0  # oldest 10 dropped
    w.clear()
    assert len(w._luma) == 0 and len(w._delta) == 0
