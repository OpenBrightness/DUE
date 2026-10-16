"""64-bin Unicode histogram widget: single-line (compat) and multi-line spectrum."""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray
from textual import events
from textual.widgets import Static

from openbrightness.due.models import HISTOGRAM_BINS, LuminanceMetrics

_BARS = " ▁▂▃▄▅▆▇█"
_RENDER_ROWS = 12
_MIN_BINS = 16
_GUTTER_WIDTH = 6


def _group_bins(hist: NDArray[np.float32], width: int | None) -> NDArray[np.float32]:
    """Distribute the 64 bins into exactly `width` columns (floor of 16).

    Largest-remainder distribution: every column is used at full resolution
    instead of quantizing to 32/64 columns like naive ceil-grouping.
    """
    n = int(hist.size)
    if width is None or width >= n:
        return hist[:n]
    width = max(width, _MIN_BINS)
    base, extra = divmod(n, width)
    counts = [base + (1 if i < extra else 0) for i in range(width)]
    out = np.zeros(width, dtype=hist.dtype)
    pos = 0
    for i, count in enumerate(counts):
        out[i] = hist[pos : pos + count].sum()
        pos += count
    return out


def _render_multi_line_bars(
    m: LuminanceMetrics, rows: int = _RENDER_ROWS, width: int | None = None
) -> list[str]:
    """Vertical block-char histogram, peak-normalized, `rows` lines tall.

    Returns content rows without axis gutters; top row first. A zero histogram
    returns a single waiting line.
    """
    hist = _group_bins(m.histogram, width)
    peak = float(hist.max()) if hist.size else 0.0
    if peak <= 0:
        return ["(waiting for frames)"]
    lines: list[str] = []
    for r in range(rows - 1, -1, -1):
        cells: list[str] = []
        for value in hist:
            norm = (float(value) / peak) * rows
            if norm >= r + 1:
                cells.append("█")
            elif norm <= r:
                cells.append(" ")
            else:
                idx = round((norm - r) * (len(_BARS) - 1))
                cells.append(_BARS[min(idx, len(_BARS) - 1)])
        lines.append("".join(cells))
    return lines


def _render_y_axis(bar_rows: list[str], total_rows: int) -> list[str]:
    """Prefix bar rows with '% of peak' gutters; axis corner on the bottom row."""
    out: list[str] = []
    half = total_rows - 1 - total_rows // 2
    for i, line in enumerate(bar_rows):
        if i == 0:
            gutter = "100% │"
        elif i == half:
            gutter = " 50% │"
        elif i == len(bar_rows) - 1:
            gutter = "  0% └"
        else:
            gutter = "     │"
        out.append(gutter + line)
    return out


def _value_to_col(value: float, width: int) -> int:
    return round(float(value) / 255.0 * (width - 1))


def _render_axis(width: int) -> list[str]:
    """X-axis ruler with threshold ticks and labels (content rows, no gutter)."""
    thresholds = ((0.0, "0"), (51.0, "Dark 51"), (128.0, "128"), (204.0, "Bright 204"), (255.0, "255"))
    ruler = ["─"] * width
    label_cells = [" "] * width
    next_free = 0
    for value, text in thresholds:
        col = _value_to_col(value, width)
        ruler[col] = "┴"
        start = min(col, max(width - len(text), 0))
        start = max(start, next_free)
        end = min(start + len(text), width)
        if end - start < len(text):
            continue  # drop truncated edge labels rather than mangle them
        label_cells[start:end] = list(text)
        next_free = end + 1
    return ["".join(ruler), "".join(label_cells)]


def _render_percentile_markers(m: LuminanceMetrics, width: int) -> list[str]:
    """Caret markers for P10/P50/P90 with merged labels on collision (G5)."""
    markers = (
        ("P10", m.p10_luminance),
        ("P50", m.median_luminance),
        ("P90", m.p90_luminance),
    )
    carets = [" "] * width
    groups: list[tuple[int, str]] = []
    for label, value in markers:
        col = _value_to_col(value, width)
        carets[col] = "▲"
        if groups:
            prev_col, prev_label = groups[-1]
            if col < prev_col + len(prev_label) + 1:
                groups[-1] = (prev_col, f"{prev_label}/{label}")
                continue
        groups.append((col, label))
    label_cells = [" "] * width
    next_free = 0
    for col, text in groups:
        start = min(col, max(width - len(text), 0))
        start = max(start, next_free)
        end = min(start + len(text), width)
        if end - start < len(text):
            continue  # drop truncated edge labels rather than mangle them
        label_cells[start:end] = list(text)
        next_free = end + 1
    return ["".join(carets), "".join(label_cells)]


class HistogramWidget(Static):
    """Renders the luminance histogram as a multi-line Unicode spectrum."""

    DEFAULT_CSS = """
    HistogramWidget {
        height: auto;
    }
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._last: LuminanceMetrics | None = None
        self._last_width = -1

    def on_mount(self) -> None:
        self.update("  (waiting for frames)")

    def on_resize(self, event: events.Resize) -> None:
        if self._last is not None and self.size.width != self._last_width:
            self._render_metrics(self._last)

    def show_metrics(self, m: LuminanceMetrics) -> None:
        self._last = m
        self._render_metrics(m)

    def _chart_width(self) -> int:
        return max(self.size.width - _GUTTER_WIDTH, _MIN_BINS)

    def _render_metrics(self, m: LuminanceMetrics) -> None:
        self._last_width = self.size.width
        width = self._chart_width()
        zero = float(m.histogram.max()) <= 0
        if zero:
            self.update("  (waiting for frames)")
            return
        bars = _render_multi_line_bars(m, rows=_RENDER_ROWS, width=width)
        axis_rows = _render_y_axis(bars, _RENDER_ROWS)
        ruler, axis_labels = _render_axis(width)
        carets, marker_labels = _render_percentile_markers(m, width)
        pad = " " * _GUTTER_WIDTH
        lines = axis_rows + [pad + ruler, pad + axis_labels, pad + carets, pad + marker_labels]
        self.update("\n".join(lines))

    @staticmethod
    def _render_bars(m: LuminanceMetrics) -> str:
        hist = m.histogram
        peak = float(hist.max())
        if peak <= 0:
            return "  (empty)"
        chars: list[str] = []
        for value in hist[:HISTOGRAM_BINS]:
            level = round(float(value) / peak * (len(_BARS) - 1))
            chars.append(_BARS[min(level, len(_BARS) - 1)])
        return "".join(chars)
