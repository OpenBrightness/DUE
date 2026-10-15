"""Capture backend abstraction (PLAN.md section 2)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from openbrightness.due.models import DisplayFrame, OutputInfo

FrameCallback = Callable[[DisplayFrame], None]
ErrorCallback = Callable[[Exception], None]


class CaptureError(RuntimeError):
    """Base class for capture failures."""


class PermissionDeniedError(CaptureError):
    """The user (or policy) denied screen capture access."""


class BackendUnavailableError(CaptureError):
    """The backend's session service is missing or unusable."""


class DisplayDisconnectedError(CaptureError):
    """The captured display or stream went away."""


class DisplayCaptureBackend(ABC):
    """A source of ~1 FPS :class:`DisplayFrame` objects.

    Contract: ``on_frame`` is invoked on the backend's own thread (GLib loop
    or timer). Callbacks must be fast and must not block; the coordinator
    hands frames off via a drop-oldest queue (PLAN.md section 5).
    """

    def __init__(self, output: OutputInfo) -> None:
        self._output = output

    @property
    def output(self) -> OutputInfo:
        return self._output

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend identifier, e.g. ``mutter``, ``portal``, ``mock``."""

    @abstractmethod
    def start(self, on_frame: FrameCallback, on_error: ErrorCallback | None = None) -> None:
        """Begin delivering frames. Raises :class:`CaptureError` on failure."""

    @abstractmethod
    def stop(self) -> None:
        """Stop capture and release all resources. Idempotent."""
