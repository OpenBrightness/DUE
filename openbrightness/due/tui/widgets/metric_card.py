"""Metric display cards for the dashboard."""

from __future__ import annotations

from textual.widgets import Static

from openbrightness.due.models import LuminanceMetrics


class LuminanceCard(Static):
    """Headline luminance figures."""

    DEFAULT_CSS = """
    LuminanceCard {
        height: auto;
        padding: 1 2;
        border: round $primary;
    }
    """

    def on_mount(self) -> None:
        self.update("Waiting for frames…")

    def show_metrics(self, m: LuminanceMetrics) -> None:
        self.update(
            f"[b]Luminance[/b]\n"
            f"  mean    {m.mean_luminance:7.2f}\n"
            f"  median  {m.median_luminance:7.2f}\n"
            f"  P10     {m.p10_luminance:7.2f}\n"
            f"  P90     {m.p90_luminance:7.2f}"
        )


class DistributionCard(Static):
    """Dark/bright ratios, contrast, and temporal activity."""

    DEFAULT_CSS = """
    DistributionCard {
        height: auto;
        padding: 1 2;
        border: round $accent;
    }
    """

    def on_mount(self) -> None:
        self.update("Waiting for frames…")

    def show_metrics(self, m: LuminanceMetrics) -> None:
        delta = "  —  " if m.temporal_delta is None else f"{m.temporal_delta:6.4f}"
        self.update(
            f"[b]Distribution[/b]\n"
            f"  dark (<51)    {m.dark_ratio * 100:6.2f}%\n"
            f"  bright (>204) {m.bright_ratio * 100:6.2f}%\n"
            f"  RMS contrast  {m.rms_contrast_normalized:6.4f}\n"
            f"  temporal Δ    {delta}"
        )
