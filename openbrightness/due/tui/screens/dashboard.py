"""Live metrics dashboard screen."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from openbrightness.due.models import LuminanceMetrics
from openbrightness.due.tui.widgets.histogram import HistogramWidget
from openbrightness.due.tui.widgets.metric_card import DistributionCard, LuminanceCard
from openbrightness.due.tui.widgets.status_bar import StatusBanner, TelemetryFooter


class DashboardScreen(Screen[None]):
    """In-place dashboard: header, cards, histogram, banner, telemetry footer."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("space", "toggle_pause", "Pause/Resume"),
        ("p", "toggle_pause", "Pause/Resume"),
        ("s", "switch_display", "Switch display"),
        ("r", "reset_temporal", "Reset temporal"),
        ("q", "quit_app", "Quit"),
    ]

    DEFAULT_CSS = """
    DashboardScreen {
        layout: vertical;
    }
    #body {
        height: 1fr;
        padding: 0 1;
    }
    #cards {
        width: 42;
        height: auto;
    }
    #histogram-panel {
        width: 1fr;
        height: auto;
        padding: 1 2;
        border: round $panel;
    }
    """

    def __init__(self, display_label: str = "") -> None:
        super().__init__()
        self._display_label = display_label
        self._paused = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="body"):
            with Vertical(id="cards"):
                yield LuminanceCard(id="luminance-card")
                yield DistributionCard(id="distribution-card")
            with Vertical(id="histogram-panel"):
                yield Static("[b]Luminance distribution[/b]", id="histogram-title")
                yield HistogramWidget(id="histogram")
        yield StatusBanner(id="status-banner")
        yield TelemetryFooter(id="telemetry")
        yield Footer()

    def on_mount(self) -> None:
        if self._display_label:
            self.query_one("#histogram-title", Static).update(
                f"[b]Luminance distribution[/b] — {self._display_label}"
            )

    def show_metrics(
        self,
        metrics: LuminanceMetrics,
        frames_processed: int = 0,
        frames_dropped: int = 0,
    ) -> None:
        self.query_one("#luminance-card", LuminanceCard).show_metrics(metrics)
        self.query_one("#distribution-card", DistributionCard).show_metrics(metrics)
        self.query_one("#histogram", HistogramWidget).show_metrics(metrics)
        self.query_one("#telemetry", TelemetryFooter).show_metrics(
            metrics,
            frames_processed=frames_processed,
            frames_dropped=frames_dropped,
            paused=self._paused,
        )

    def show_notice(self, message: str, level: str = "info") -> None:
        self.query_one("#status-banner", StatusBanner).show_notice(message, level)

    def clear_notice(self) -> None:
        self.query_one("#status-banner", StatusBanner).clear_notice()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def action_toggle_pause(self) -> None:
        self.post_message(self.TogglePause())

    def action_switch_display(self) -> None:
        self.post_message(self.SwitchDisplay())

    def action_reset_temporal(self) -> None:
        self.post_message(self.ResetTemporal())

    def action_quit_app(self) -> None:
        self.post_message(self.QuitApp())

    class TogglePause(Message):
        pass

    class SwitchDisplay(Message):
        pass

    class ResetTemporal(Message):
        pass

    class QuitApp(Message):
        pass
