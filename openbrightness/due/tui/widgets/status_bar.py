"""Telemetry footer and status/error banner."""

from __future__ import annotations

from textual.widgets import Static

from openbrightness.due.models import LuminanceMetrics

_ERROR_LEVELS = ("info", "warning", "error")


class TelemetryFooter(Static):
    """Latency, throughput, and pipeline state."""

    DEFAULT_CSS = """
    TelemetryFooter {
        height: 1;
        padding: 0 1;
        background: $surface;
    }
    """

    def on_mount(self) -> None:
        self.update("idle")

    def show_metrics(
        self,
        m: LuminanceMetrics,
        frames_processed: int = 0,
        frames_dropped: int = 0,
        paused: bool = False,
    ) -> None:
        state = "PAUSED" if paused else "LIVE"
        total = m.capture_latency_ms + m.analysis_latency_ms
        self.update(
            f" {state}  cap {m.capture_latency_ms:6.2f} ms  "
            f"ana {m.analysis_latency_ms:6.2f} ms  tot {total:6.2f} ms  "
            f"frames {frames_processed}  dropped {frames_dropped}"
        )


class StatusBanner(Static):
    """Surface for notices and recoverable errors (M6)."""

    DEFAULT_CSS = """
    StatusBanner {
        height: 1;
        padding: 0 1;
        color: $text;
        background: $surface;
    }
    StatusBanner.-warning {
        background: $warning;
        color: $text;
    }
    StatusBanner.-error {
        background: $error;
        color: $text;
    }
    """

    def on_mount(self) -> None:
        self.clear_notice()

    def show_notice(self, message: str, level: str = "info") -> None:
        if level not in _ERROR_LEVELS:
            raise ValueError(f"unknown level {level!r}; choose from {_ERROR_LEVELS}")
        self.set_class(level == "warning", "-warning")
        self.set_class(level == "error", "-error")
        self.update(message)

    def clear_notice(self) -> None:
        self.remove_class("-warning", "-error")
        self.update("")
