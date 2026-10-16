"""Display-control abstraction (PLAN.md section 11, research report section 8).

``control/*`` is decoupled from capture/analysis: it imports only
``openbrightness.due.models`` and the standard library. Only ``tui/app.py``
wires the control layer to the analysis pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict


class ControlError(Exception):
    """Base error for the display-control layer."""


class BacklightUnavailableError(ControlError):
    """No usable backlight device was found for the internal panel."""


class ControlWriteError(ControlError):
    """A brightness write failed at the hardware/D-Bus boundary."""


class DisplayControlBackend(ABC):
    """Hardware brightness channel for one display.

    All brightness values are normalized floats in [0.0, 1.0] of the device
    maximum. Implementations must never raise out of ``get_brightness`` /
    ``set_brightness`` for expected hardware failures — return ``None``/``False``
    so the policy layer can react without a crash path.
    """

    @abstractmethod
    def get_brightness(self) -> float | None:
        """Read current brightness normalized to [0, 1]; ``None`` on failure."""

    @abstractmethod
    def set_brightness(self, value: float) -> bool:
        """Write brightness normalized to [0, 1]; ``True`` on success."""

    @abstractmethod
    def describe(self) -> str:
        """Human-readable backend description for the status strip."""


class WriteLedger:
    """In-process per-connector brightness-write accounting.

    PLAN.md 11.2 requires every write to be counted so tests (and soak runs)
    can assert safety invariants — e.g. external monitors must never be
    auto-written.
    """

    def __init__(self) -> None:
        self._counts: dict[str, int] = defaultdict(int)
        self._values: dict[str, list[float]] = defaultdict(list)

    def record(self, connector: str, value: float) -> None:
        self._counts[connector] += 1
        self._values[connector].append(value)

    def count(self, connector: str | None = None) -> int:
        if connector is None:
            return sum(self._counts.values())
        return self._counts.get(connector, 0)

    def values(self, connector: str) -> list[float]:
        return list(self._values.get(connector, ()))

    def reset(self) -> None:
        self._counts.clear()
        self._values.clear()
