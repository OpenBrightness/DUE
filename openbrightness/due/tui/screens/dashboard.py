"""Live metrics dashboard screen."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.message import Message
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, Header, Static

from openbrightness.due.control.manager import ControlStatus
from openbrightness.due.models import LuminanceMetrics
from openbrightness.due.tui.widgets.control_status import ControlStatusStrip
from openbrightness.due.tui.widgets.histogram import HistogramWidget
from openbrightness.due.tui.widgets.metric_card import DistributionCard, LuminanceCard
from openbrightness.due.tui.widgets.status_bar import StatusBanner, TelemetryFooter
from openbrightness.due.tui.widgets.trend import TrendWidget

_NARROW_THRESHOLD = 105


class DashboardScreen(Screen[None]):
    """In-place dashboard: header, cards, visual panel, banner, telemetry footer."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("space", "toggle_pause", "Pause/Resume"),
        ("p", "toggle_pause", "Pause/Resume"),
        ("a", "toggle_auto", "Auto-adjust"),
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
        padding: 0 2;
        align: center middle;
        overflow-y: auto;
    }
    #body.-top-aligned {
        align: center top;
    }
    #dashboard-container {
        width: auto;
        max-width: 124;
        height: auto;
        layout: horizontal;
    }
    #dashboard-container.-narrow {
        layout: vertical;
    }
    #cards {
        width: 44;
        height: auto;
        margin-right: 1;
    }
    #visual-panel {
        width: 76;
        height: auto;
    }
    #histogram-panel {
        height: auto;
        padding: 1 1;
        border: round $panel;
    }
    """

    def __init__(self, display_label: str = "") -> None:
        super().__init__()
        self._display_label = display_label
        self._paused = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="body"), Vertical(id="dashboard-container"):
            with Vertical(id="cards"):
                yield LuminanceCard(id="luminance-card")
                yield DistributionCard(id="distribution-card")
            with Vertical(id="visual-panel"):
                with Vertical(id="histogram-panel"):
                    yield Static("[b]Luminance distribution[/b]", id="histogram-title")
                    yield HistogramWidget(id="histogram")
                yield TrendWidget(id="trend")
        yield ControlStatusStrip(id="control-status")
        yield StatusBanner(id="status-banner")
        yield TelemetryFooter(id="telemetry")
        yield Footer()

    def on_mount(self) -> None:
        title = self._find("#histogram-title")
        if self._display_label and isinstance(title, Static):
            title.update(f"[b]Luminance distribution[/b] — {self._display_label}")
        self._apply_responsive()

    def on_resize(self, event: Resize) -> None:
        self._apply_responsive()

    def _find(self, selector: str) -> object | None:
        """Non-raising widget lookup (safe while children are still mounting)."""
        return next(iter(self.query(selector)), None)

    def _apply_responsive(self) -> None:
        """G1: stack columns under 105 cols; G2: center when content fits,
        top-align + scroll when it overflows (align-middle would clip the top)."""
        body = self._find("#body")
        container = self._find("#dashboard-container")
        if not isinstance(body, Widget) or not isinstance(container, Widget):
            return
        container.set_class(self.size.width < _NARROW_THRESHOLD, "-narrow")
        content_height = container.virtual_size.height
        body.set_class(content_height > body.size.height, "-top-aligned")

    def show_metrics(
        self,
        metrics: LuminanceMetrics,
        frames_processed: int = 0,
        frames_dropped: int = 0,
    ) -> None:
        luminance = self._find("#luminance-card")
        distribution = self._find("#distribution-card")
        histogram = self._find("#histogram")
        trend = self._find("#trend")
        telemetry = self._find("#telemetry")
        if (
            not isinstance(luminance, LuminanceCard)
            or not isinstance(distribution, DistributionCard)
            or not isinstance(histogram, HistogramWidget)
            or not isinstance(trend, TrendWidget)
            or not isinstance(telemetry, TelemetryFooter)
        ):
            return  # children still mounting; next frame will update them
        luminance.show_metrics(metrics)
        distribution.show_metrics(metrics)
        histogram.show_metrics(metrics)
        trend.show_metrics(metrics)
        telemetry.show_metrics(
            metrics,
            frames_processed=frames_processed,
            frames_dropped=frames_dropped,
            paused=self._paused,
        )
        self.call_after_refresh(self._apply_responsive)

    def show_notice(self, message: str, level: str = "info") -> None:
        banner = self._find("#status-banner")
        if isinstance(banner, StatusBanner):
            banner.show_notice(message, level)

    def clear_notice(self) -> None:
        banner = self._find("#status-banner")
        if isinstance(banner, StatusBanner):
            banner.clear_notice()

    def clear_trends(self) -> None:
        trend = self._find("#trend")
        if isinstance(trend, TrendWidget):
            trend.clear()

    def show_control_status(self, status: ControlStatus) -> None:
        strip = self._find("#control-status")
        if isinstance(strip, ControlStatusStrip):
            strip.show_status(status)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def action_toggle_pause(self) -> None:
        self.post_message(self.TogglePause())

    def action_switch_display(self) -> None:
        self.post_message(self.SwitchDisplay())

    def action_reset_temporal(self) -> None:
        self.clear_trends()
        self.post_message(self.ResetTemporal())

    def action_toggle_auto(self) -> None:
        self.post_message(self.ToggleAuto())

    def action_quit_app(self) -> None:
        self.post_message(self.QuitApp())

    class TogglePause(Message):
        pass

    class ToggleAuto(Message):
        pass

    class SwitchDisplay(Message):
        pass

    class ResetTemporal(Message):
        pass

    class QuitApp(Message):
        pass
