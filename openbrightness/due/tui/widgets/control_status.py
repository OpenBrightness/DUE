"""One-row auto-adjust status strip (PLAN.md section 11.3)."""

from __future__ import annotations

from textual.widgets import Static

from openbrightness.due.control.manager import ControlStatus


def _fmt_pct(value: float | None) -> str:
    return "  —  " if value is None else f"{value * 100:3.0f}%"


class ControlStatusStrip(Static):
    """Shows auto-adjust state: baseline/target/applied or inhibit countdown."""

    DEFAULT_CSS = """
    ControlStatusStrip {
        height: 1;
        padding: 0 1;
        background: $surface;
        color: $text-muted;
    }
    ControlStatusStrip.-active {
        color: $success;
    }
    ControlStatusStrip.-inhibited {
        color: $warning;
    }
    """

    def on_mount(self) -> None:
        self.show_status(ControlStatus(auto_enabled=False, supported=False))

    def show_status(self, status: ControlStatus) -> None:
        if not status.supported:
            self.remove_class("-active", "-inhibited")
            self.update(" AUTO  n/a — no internal backlight on this display")
            return
        if status.inhibited_until is not None:
            import time

            remaining = max(0.0, status.inhibited_until - time.monotonic())
            mins, secs = divmod(int(remaining), 60)
            self.remove_class("-active")
            self.add_class("-inhibited")
            self.update(f" AUTO  INHIBITED {mins}:{secs:02d} — manual change detected")
            return
        self.remove_class("-inhibited")
        if not status.auto_enabled:
            self.remove_class("-active")
            self.update(" AUTO  OFF  — press A to enable content-adaptive dimming")
            return
        self.add_class("-active")
        self.update(
            f" AUTO  ON  baseline {_fmt_pct(status.baseline)}  "
            f"target {_fmt_pct(status.target)}  applied {_fmt_pct(status.applied)}"
        )
