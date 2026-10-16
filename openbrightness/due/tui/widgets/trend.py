"""Rolling trend sparklines for luminance and temporal motion."""

from __future__ import annotations

from collections import deque
from typing import Any

from textual.app import ComposeResult
from textual.widgets import Label, Sparkline, Static

from openbrightness.due.models import LuminanceMetrics

_WINDOW = 30
_LUMA_SCALE = 255.0
_DELTA_SCALE = 1.0


class TrendWidget(Static):
    """30-sample rolling trends: mean luminance and temporal motion (G7/G8)."""

    DEFAULT_CSS = """
    TrendWidget {
        layout: vertical;
        height: auto;
        padding: 1 1;
        border: round $accent;
    }
    TrendWidget Label {
        color: $text-muted;
    }
    TrendWidget Sparkline {
        height: 1;
        background: $surface;
    }
    TrendWidget Sparkline > .sparkline--min-color {
        color: $accent;
    }
    TrendWidget Sparkline > .sparkline--max-color {
        color: $warning;
    }
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._luma: deque[float] = deque(maxlen=_WINDOW)
        self._delta: deque[float] = deque(maxlen=_WINDOW)

    def compose(self) -> ComposeResult:
        yield Label("Luminance trend (last 30 samples)", id="luma-trend-label")
        yield Sparkline(id="luma-sparkline", summary_function=lambda data: _LUMA_SCALE)
        yield Label("Motion trend (last 30 samples)", id="delta-trend-label")
        yield Sparkline(id="delta-sparkline", summary_function=lambda data: _DELTA_SCALE)

    def show_metrics(self, m: LuminanceMetrics) -> None:
        self._luma.append(m.mean_luminance)
        if m.temporal_delta is not None:
            self._delta.append(m.temporal_delta)
        self._sync()

    def clear(self) -> None:
        self._luma.clear()
        self._delta.clear()
        self._sync()

    def _sync(self) -> None:
        if not self.is_mounted:
            return
        self.query_one("#luma-sparkline", Sparkline).data = list(self._luma) or None
        self.query_one("#delta-sparkline", Sparkline).data = list(self._delta) or None
