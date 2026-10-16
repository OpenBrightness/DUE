"""DueApp — the Textual application shell (PLAN.md sections 5–6)."""

from __future__ import annotations

import logging
from collections.abc import Callable

from textual import on
from textual.app import App
from textual.message import Message

from openbrightness.due.capture.base import CaptureError, DisplayCaptureBackend
from openbrightness.due.control.base import (
    BacklightUnavailableError,
    DisplayControlBackend,
    WriteLedger,
)
from openbrightness.due.control.config import AutoAdjustConfig, save_config
from openbrightness.due.control.logind import LogindBacklightBackend
from openbrightness.due.control.manager import ControlManager, ControlStatus
from openbrightness.due.control.policy import PolicyConfig
from openbrightness.due.coordinator import PipelineCoordinator
from openbrightness.due.models import LuminanceMetrics, OutputInfo
from openbrightness.due.tui.screens.dashboard import DashboardScreen
from openbrightness.due.tui.screens.select import DisplaySelectScreen

log = logging.getLogger(__name__)

BackendFactory = Callable[[OutputInfo], DisplayCaptureBackend]
ControlFactory = Callable[[OutputInfo], DisplayControlBackend | None]


class MetricsMessage(Message):
    def __init__(self, metrics: LuminanceMetrics) -> None:
        super().__init__()
        self.metrics = metrics


class ErrorMessage(Message):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error


class ControlStatusMessage(Message):
    def __init__(self, status: ControlStatus) -> None:
        super().__init__()
        self.status = status


class DueApp(App[None]):
    """Live display-analysis dashboard."""

    TITLE = "OpenBrightness DUE"

    def __init__(
        self,
        outputs: list[OutputInfo],
        backend_factory: BackendFactory,
        initial_output: OutputInfo | None = None,
        control_factory: ControlFactory | None = None,
        auto_config: AutoAdjustConfig | None = None,
    ) -> None:
        super().__init__()
        self._outputs = outputs
        self._backend_factory = backend_factory
        self._initial_output = initial_output
        self._control_factory = control_factory
        self._auto_config = auto_config or AutoAdjustConfig()
        self._coordinator: PipelineCoordinator | None = None
        self._backend: DisplayCaptureBackend | None = None
        self._control: ControlManager | None = None
        self._write_ledger = WriteLedger()
        self._control_enabled = self._auto_config.auto_enabled

    def on_mount(self) -> None:
        if self._initial_output is not None:
            self._start_capture(self._initial_output)
        else:
            self.push_screen(DisplaySelectScreen(self._outputs))

    def on_unmount(self) -> None:
        self._teardown()

    # ---- capture lifecycle -------------------------------------------------

    def _start_capture(self, output: OutputInfo) -> None:
        self._teardown()

        def on_metrics(m: LuminanceMetrics) -> None:
            if self._control is not None:
                self._control.on_metrics(m)
            self.post_message(MetricsMessage(m))

        def on_error(e: Exception) -> None:
            self.post_message(ErrorMessage(e))

        def on_control_status(status: ControlStatus) -> None:
            self.post_message(ControlStatusMessage(status))

        coordinator = PipelineCoordinator(on_metrics=on_metrics, on_error=on_error)
        coordinator.start()
        self._control = self._start_control(output, on_control_status)
        backend = self._backend_factory(output)
        try:
            backend.start(on_frame=coordinator.submit, on_error=on_error)
        except CaptureError as exc:
            coordinator.stop()
            log.warning("capture start failed: %s", exc)
            self.post_message(ErrorMessage(exc))
            self.push_screen(DisplaySelectScreen(self._outputs))
            return
        self._coordinator = coordinator
        self._backend = backend
        self.push_screen(DashboardScreen(display_label=output.label))

    def _start_control(
        self, output: OutputInfo, on_status: Callable[[ControlStatus], None]
    ) -> ControlManager | None:
        """Build the control manager — internal panels only (11.6 invariant 5)."""
        if not output.is_internal:
            return None
        backend: DisplayControlBackend | None = None
        try:
            if self._control_factory is not None:
                backend = self._control_factory(output)
            else:
                backend = LogindBacklightBackend()
        except BacklightUnavailableError as exc:
            log.debug("no backlight backend for %s: %s", output.connector, exc)
        manager = ControlManager(
            backend,
            connector=output.connector,
            policy_config=PolicyConfig(
                factor_min=self._auto_config.factor_min,
                alpha=self._auto_config.alpha,
                motion_freeze_threshold=self._auto_config.motion_freeze_threshold,
            ),
            ledger=self._write_ledger,
            on_status=on_status,
        )
        if self._control_enabled:
            manager.enable()
        return manager

    def _teardown(self) -> None:
        if self._control is not None:
            self._control.stop()  # brightness intentionally kept (decision 2)
            self._control = None
        if self._backend is not None:
            self._backend.stop()
            self._backend = None
        if self._coordinator is not None:
            self._coordinator.stop()
            self._coordinator = None

    def _switch_display(self) -> None:
        self._teardown()
        if len(self.screen_stack) > 1:
            self.pop_screen()
        self.push_screen(DisplaySelectScreen(self._outputs))

    # ---- message handlers -------------------------------------------------

    @on(MetricsMessage)
    def _handle_metrics(self, message: MetricsMessage) -> None:
        screen = self.screen
        if isinstance(screen, DashboardScreen) and self._coordinator is not None:
            screen.show_metrics(
                message.metrics,
                frames_processed=self._coordinator.frames_processed,
                frames_dropped=self._coordinator.frames_dropped,
            )

    @on(ErrorMessage)
    def _handle_error(self, message: ErrorMessage) -> None:
        screen = self.screen
        if isinstance(screen, DashboardScreen):
            screen.show_notice(f"{message.error}", level="error")

    @on(ControlStatusMessage)
    def _handle_control_status(self, message: ControlStatusMessage) -> None:
        screen = self.screen
        if isinstance(screen, DashboardScreen):
            screen.show_control_status(message.status)

    @on(DashboardScreen.ToggleAuto)
    def _handle_toggle_auto(self) -> None:
        if self._control is None:
            screen = self.screen
            if isinstance(screen, DashboardScreen):
                screen.show_notice(
                    "Auto-adjust unavailable on external displays", level="warning"
                )
            return
        enabled = self._control.toggle()
        self._control_enabled = enabled
        self._auto_config = AutoAdjustConfig(
            auto_enabled=enabled,
            baseline=self._control.status().baseline,
            factor_min=self._auto_config.factor_min,
            alpha=self._auto_config.alpha,
            motion_freeze_threshold=self._auto_config.motion_freeze_threshold,
        )
        try:
            save_config(self._auto_config)
        except OSError as exc:
            log.warning("could not persist auto-adjust state: %s", exc)
        screen = self.screen
        if isinstance(screen, DashboardScreen):
            status = self._control.status()
            screen.show_control_status(status)
            if status.supported:
                baseline = status.baseline
                pct = "—" if baseline is None else f"{baseline * 100:.0f}%"
                screen.show_notice(
                    f"Auto-adjust {'ON' if enabled else 'OFF'} — baseline {pct}"
                    if enabled
                    else "Auto-adjust OFF — baseline restored",
                    level="info",
                )

    @on(DashboardScreen.TogglePause)
    def _handle_toggle_pause(self) -> None:
        self._toggle_pause()

    @on(DashboardScreen.SwitchDisplay)
    def _handle_switch_display(self) -> None:
        self._switch_display()

    @on(DashboardScreen.ResetTemporal)
    def _handle_reset_temporal(self) -> None:
        if self._coordinator is not None:
            self._coordinator.reset_temporal()
            screen = self.screen
            if isinstance(screen, DashboardScreen):
                screen.show_notice("Temporal statistics reset", level="info")

    @on(DashboardScreen.QuitApp)
    @on(DisplaySelectScreen.QuitApp)
    def _handle_quit(self) -> None:
        self.exit()

    @on(DisplaySelectScreen.DisplayChosen)
    def _handle_display_chosen(self, message: DisplaySelectScreen.DisplayChosen) -> None:
        self.pop_screen()
        self._start_capture(message.output)

    def _toggle_pause(self) -> None:
        if self._coordinator is None:
            return
        if self._coordinator.paused:
            self._coordinator.resume()
            paused = False
        else:
            self._coordinator.pause()
            paused = True
        screen = self.screen
        if isinstance(screen, DashboardScreen):
            screen.set_paused(paused)
            screen.show_notice("Paused" if paused else "Resumed", level="info")
