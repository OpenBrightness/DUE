"""Metric display cards for the dashboard."""

from __future__ import annotations

from textual.widgets import Static

from openbrightness.due.models import LuminanceMetrics

MOTION_STATIC_MAX = 0.005
MOTION_LIGHT_MAX = 0.05
_BAR_WIDTH = 16
_COMPOSITION_WIDTH = 30


def _render_bar(value: float, max_val: float = 255.0, width: int = _BAR_WIDTH) -> str:
    filled = round(max(value / max_val, 0.0) * width)
    return f"[{'█' * filled}{'░' * (width - filled)}]"


def motion_tag(delta: float | None) -> str:
    """Qualitative motion tier for a temporal delta (G6 thresholds)."""
    if delta is None:
        return "—"
    if delta <= MOTION_STATIC_MAX:
        return "Static"
    if delta <= MOTION_LIGHT_MAX:
        return "Light motion"
    return "Active motion"


def _render_composition_bar(dark: float, bright: float, width: int = _COMPOSITION_WIDTH) -> str:
    """Segmented dark/mid/bright bar; segments always sum to `width` (G12)."""
    mid = max(1.0 - (dark + bright), 0.0)
    exact = [dark * width, mid * width, bright * width]
    lengths = [int(x) for x in exact]
    remainder = width - sum(lengths)
    by_fraction = sorted(range(3), key=lambda i: exact[i] - lengths[i], reverse=True)
    for i in by_fraction[: max(remainder, 0)]:
        lengths[i] += 1
    d_len, m_len, b_len = lengths
    return (
        f"[dim]D:[/][bold cyan]{'█' * d_len}[/]"
        f"[dim]M:[/][bold green]{'░' * m_len}[/]"
        f"[dim]B:[/][bold yellow]{'▒' * b_len}[/]"
    )


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
            f"  mean    {m.mean_luminance:7.2f} {_render_bar(m.mean_luminance)}\n"
            f"  median  {m.median_luminance:7.2f} {_render_bar(m.median_luminance)}\n"
            f"  P10     {m.p10_luminance:7.2f}\n"
            f"  P90     {m.p90_luminance:7.2f}\n"
            f"  dyn rng {m.p90_luminance - m.p10_luminance:7.2f}"
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
            f"  {_render_composition_bar(m.dark_ratio, m.bright_ratio)}\n"
            f"  RMS contrast  {m.rms_contrast_normalized:6.4f}\n"
            f"  temporal Δ    {delta}  {motion_tag(m.temporal_delta)}"
        )
