"""64-bin Unicode bar histogram widget."""

from __future__ import annotations

from textual.widgets import Static

from openbrightness.due.models import HISTOGRAM_BINS, LuminanceMetrics

_BARS = " ▁▂▃▄▅▆▇█"


class HistogramWidget(Static):
    """Renders the luminance histogram as a row of Unicode bars."""

    DEFAULT_CSS = """
    HistogramWidget {
        height: auto;
        padding: 1 2;
        border: round $panel;
    }
    """

    def on_mount(self) -> None:
        self.update("[b]Histogram[/b]\n  Waiting for frames…")

    def show_metrics(self, m: LuminanceMetrics) -> None:
        self.update(f"[b]Histogram[/b]\n  {self._render_bars(m)}")

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
