"""Headless Textual tests for the dashboard, picker, and app wiring."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import numpy as np
import pytest

from openbrightness.due.capture.mock import MockCaptureBackend
from openbrightness.due.models import LuminanceMetrics, OutputInfo
from openbrightness.due.tui.app import DueApp
from openbrightness.due.tui.screens.dashboard import DashboardScreen
from openbrightness.due.tui.screens.select import DisplaySelectScreen
from openbrightness.due.tui.widgets.histogram import HistogramWidget
from openbrightness.due.tui.widgets.status_bar import StatusBanner, TelemetryFooter

OUTPUTS = [
    OutputInfo("eDP-1", "BOE", "NE160QDM-NY1", 1920, 1200, 60.0, is_primary=True),
    OutputInfo("HDMI-A-1", "LG", "27GN800", 2560, 1440, 144.0),
]


def run(coro: Coroutine[Any, Any, None]) -> None:
    asyncio.run(coro)


def make_metrics(delta: float | None = None) -> LuminanceMetrics:
    hist = np.zeros(64, dtype=np.float32)
    hist[32] = 1.0
    return LuminanceMetrics(
        mean_luminance=128.0,
        median_luminance=128.0,
        p10_luminance=40.0,
        p90_luminance=220.0,
        dark_ratio=0.1,
        bright_ratio=0.2,
        rms_contrast=55.5,
        temporal_delta=delta,
        histogram=hist,
        capture_latency_ms=4.2,
        analysis_latency_ms=0.9,
        width=480,
        height=300,
        timestamp_monotonic_ns=0,
    )


def make_zero_metrics() -> LuminanceMetrics:
    return LuminanceMetrics(
        mean_luminance=0.0,
        median_luminance=0.0,
        p10_luminance=0.0,
        p90_luminance=0.0,
        dark_ratio=1.0,
        bright_ratio=0.0,
        rms_contrast=0.0,
        temporal_delta=None,
        histogram=np.zeros(64, dtype=np.float32),
        capture_latency_ms=0.0,
        analysis_latency_ms=0.0,
        width=4,
        height=4,
        timestamp_monotonic_ns=0,
    )


def mock_factory(output: OutputInfo) -> MockCaptureBackend:
    return MockCaptureBackend(output, fps=20.0, width=64, height=48)


def test_dashboard_renders_metrics() -> None:
    async def scenario() -> None:
        app = DueApp(OUTPUTS, mock_factory, initial_output=OUTPUTS[0])
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            assert app._coordinator is not None
            app._coordinator.pause()
            screen = app.screen
            assert isinstance(screen, DashboardScreen)
            screen.show_metrics(make_metrics(delta=0.0123))
            await pilot.pause()
            text = str(screen.query_one("#luminance-card").render())
            assert "128.00" in text
            dist = str(screen.query_one("#distribution-card").render())
            assert "RMS contrast" in dist
            assert "0.0123" in dist

    run(scenario())


def test_histogram_rendering() -> None:
    bars = HistogramWidget._render_bars(make_metrics())
    assert len(bars) == 64
    assert "empty" in HistogramWidget._render_bars(make_zero_metrics())


def test_status_banner_rejects_unknown_level() -> None:
    banner = StatusBanner()
    with pytest.raises(ValueError, match="level"):
        banner.show_notice("x", level="nope")


def test_telemetry_footer_formats() -> None:
    footer = TelemetryFooter()
    footer.show_metrics(make_metrics(), frames_processed=7, frames_dropped=2, paused=True)
    text = str(footer.render())
    assert "PAUSED" in text
    assert "dropped 2" in text


def test_select_screen_lists_outputs() -> None:
    async def scenario() -> None:
        app = DueApp(OUTPUTS, mock_factory)
        async with app.run_test() as pilot:
            screen = app.screen
            assert isinstance(screen, DisplaySelectScreen)
            await pilot.pause()
            assert len(screen.query("DisplayListItem")) == 2

    run(scenario())


def test_select_screen_shows_internal_external_labels() -> None:
    async def scenario() -> None:
        app = DueApp(OUTPUTS, mock_factory)
        async with app.run_test() as pilot:
            await pilot.pause()
            text = "\n".join(
                str(label.render()) for label in app.screen.query("DisplayListItem Label")
            )
            assert "[Internal] eDP-1" in text
            assert "[External] HDMI-A-1" in text
            assert "●" in text

    run(scenario())


def test_dashboard_has_redesign_dom() -> None:
    async def scenario() -> None:
        app = DueApp(OUTPUTS, mock_factory, initial_output=OUTPUTS[0])
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            screen = app.screen
            assert isinstance(screen, DashboardScreen)
            assert screen.query_one("#dashboard-container")
            assert screen.query_one("#visual-panel")
            assert screen.query_one("#trend")

    run(scenario())


def test_trend_widget_receives_metrics() -> None:
    async def scenario() -> None:
        app = DueApp(OUTPUTS, mock_factory, initial_output=OUTPUTS[0])
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            app._teardown()  # stop capture; this test drives the widget directly
            screen = app.screen
            assert isinstance(screen, DashboardScreen)
            screen.clear_trends()
            for _ in range(5):
                screen.show_metrics(make_metrics(delta=0.01))
            await pilot.pause()
            trend = screen.query_one("#trend")
            assert len(trend._luma) == 5
            assert len(trend._delta) == 5
            await pilot.press("r")
            await pilot.pause()
            assert len(trend._luma) == 0

    run(scenario())


def test_dashboard_top_aligned_when_content_overflows() -> None:
    async def scenario() -> None:
        app = DueApp(OUTPUTS, mock_factory, initial_output=OUTPUTS[0])
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(0.3)
            app._teardown()  # deterministic content: drive metrics directly
            screen = app.screen
            assert isinstance(screen, DashboardScreen)
            for _ in range(3):
                screen.show_metrics(make_metrics(delta=0.01))
            await pilot.pause()
            body = screen.query_one("#body")
            container = screen.query_one("#dashboard-container")
            assert container.has_class("-narrow")  # 80 < 105 → stacked
            assert body.has_class("-top-aligned")  # overflow → scrollable top
            assert body.styles.overflow_y == "auto"

    run(scenario())


def test_dashboard_centered_and_side_by_side_when_large() -> None:
    async def scenario() -> None:
        app = DueApp(OUTPUTS, mock_factory, initial_output=OUTPUTS[0])
        async with app.run_test(size=(150, 46)) as pilot:
            await pilot.pause(0.3)
            app._teardown()  # deterministic content: drive metrics directly
            screen = app.screen
            assert isinstance(screen, DashboardScreen)
            for _ in range(3):
                screen.show_metrics(make_metrics(delta=0.01))
            await pilot.pause()
            container = screen.query_one("#dashboard-container")
            body = screen.query_one("#body")
            assert not container.has_class("-narrow")  # side by side
            assert not body.has_class("-top-aligned")  # fits → centered
            assert body.styles.align == ("center", "middle")

    run(scenario())


def test_app_capture_and_quit() -> None:
    async def scenario() -> None:
        app = DueApp(OUTPUTS, mock_factory, initial_output=OUTPUTS[0])
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            assert isinstance(app.screen, DashboardScreen)
            assert app._backend is not None
            assert app._coordinator is not None
            await pilot.press("q")
            await pilot.pause()

    run(scenario())


def test_pause_binding_toggles_coordinator() -> None:
    async def scenario() -> None:
        app = DueApp(OUTPUTS, mock_factory, initial_output=OUTPUTS[0])
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            assert app._coordinator is not None
            assert not app._coordinator.paused
            await pilot.press("p")
            await pilot.pause()
            assert app._coordinator.paused
            await pilot.press("space")
            await pilot.pause()
            assert not app._coordinator.paused

    run(scenario())


def test_reset_temporal_binding() -> None:
    async def scenario() -> None:
        app = DueApp(OUTPUTS, mock_factory, initial_output=OUTPUTS[0])
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            await pilot.press("r")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, DashboardScreen)
            assert "reset" in str(screen.query_one("#status-banner").render()).lower()

    run(scenario())


def test_switch_display_binding() -> None:
    async def scenario() -> None:
        app = DueApp(OUTPUTS, mock_factory, initial_output=OUTPUTS[0])
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, DisplaySelectScreen)

    run(scenario())
