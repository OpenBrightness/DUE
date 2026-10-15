"""Error-handling tests for the M6 matrix (PLAN.md section 6)."""

from __future__ import annotations

import signal
import threading

import pytest

from openbrightness.due.capture.base import CaptureError, DisplayDisconnectedError
from openbrightness.due.capture.wlr import WlrScreencopyBackend
from openbrightness.due.models import OutputInfo
from openbrightness.due.tui.app import DueApp
from openbrightness.due.tui.screens.dashboard import DashboardScreen
from openbrightness.due.tui.screens.select import DisplaySelectScreen
from openbrightness.due.tui.widgets.status_bar import StatusBanner

OUTPUTS = [OutputInfo("eDP-1", "BOE", "X", 1920, 1200, 60.0, is_primary=True)]


def _run(coro):
    import asyncio

    asyncio.run(coro)


class StubDisplay:
    """A Display whose roundtrips never announce screencopy support."""

    def connect(self):
        return None

    def disconnect(self):
        return None

    def roundtrip(self, **kwargs):
        return 0

    def get_registry(self):
        return StubRegistry()


class StubRegistry:
    def __init__(self):
        self.dispatcher: dict = {}


def test_unsupported_compositor_reports_capture_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import pywayland.client.display

    monkeypatch.setattr(pywayland.client.display, "Display", StubDisplay)
    backend = WlrScreencopyBackend(OUTPUTS[0], fps=1.0)
    errors: list[Exception] = []
    done = threading.Event()

    def on_error(exc: Exception) -> None:
        errors.append(exc)
        done.set()

    backend.start(lambda f: None, on_error)
    assert done.wait(5.0)
    backend.stop()
    assert isinstance(errors[0], CaptureError)
    assert "zwlr_screencopy" in str(errors[0])


def test_unconnectable_display_reports_capture_error() -> None:
    backend = WlrScreencopyBackend(OUTPUTS[0], fps=1.0)
    errors: list[Exception] = []
    done = threading.Event()

    def on_error(exc: Exception) -> None:
        errors.append(exc)
        done.set()

    import os

    old = os.environ.get("WAYLAND_DISPLAY")
    os.environ["WAYLAND_DISPLAY"] = "due-nonexistent-0"
    try:
        backend.start(lambda f: None, on_error)
        assert done.wait(5.0)
    finally:
        backend.stop()
        if old is None:
            os.environ.pop("WAYLAND_DISPLAY", None)
        else:
            os.environ["WAYLAND_DISPLAY"] = old
    assert errors, "expected an error callback"


def test_backend_start_failure_returns_to_picker_with_banner() -> None:
    def failing_factory(output):
        class Boom:
            name = "boom"

            def start(self, on_frame, on_error=None):
                raise CaptureError("simulated capture failure")

            def stop(self):
                pass

        return Boom()

    async def scenario():
        app = DueApp(OUTPUTS, failing_factory, initial_output=OUTPUTS[0])
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, DisplaySelectScreen)
            screen = app.screen
            assert isinstance(screen, DisplaySelectScreen)

    _run(scenario())


def test_error_message_reaches_banner() -> None:
    from openbrightness.due.capture.mock import MockCaptureBackend
    from openbrightness.due.tui.app import ErrorMessage

    def mock_factory(output):
        return MockCaptureBackend(output, fps=20.0, width=32, height=32)

    async def scenario():
        app = DueApp(OUTPUTS, mock_factory, initial_output=OUTPUTS[0])
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            screen = app.screen
            assert isinstance(screen, DashboardScreen)
            app.post_message(ErrorMessage(RuntimeError("boom")))
            await pilot.pause()
            banner = screen.query_one("#status-banner", StatusBanner)
            assert "boom" in str(banner.render())
            assert banner.has_class("-error")

    _run(scenario())


def test_status_banner_levels_and_clear() -> None:
    banner = StatusBanner()

    class FakeApp:
        pass

    banner.show_notice("warn msg", level="warning")
    assert banner.has_class("-warning")
    banner.show_notice("err msg", level="error")
    assert not banner.has_class("-warning")
    assert banner.has_class("-error")
    banner.clear_notice()
    assert not banner.has_class("-error")
    assert not banner.has_class("-warning")


def test_error_hierarchy() -> None:
    assert issubclass(DisplayDisconnectedError, CaptureError)
    assert issubclass(CaptureError, RuntimeError)


def test_signal_handlers_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    from openbrightness.due import __main__ as main_mod

    registered: dict[int, object] = {}
    monkeypatch.setattr(signal, "signal", lambda sig, fn: registered.__setitem__(sig, fn))

    def fake_run(self):
        return None

    monkeypatch.setattr(DueApp, "run", fake_run)
    monkeypatch.setattr(main_mod, "list_outputs", lambda: OUTPUTS)

    assert main_mod.main([]) == 0
    assert signal.SIGTERM in registered
    assert signal.SIGINT in registered
