"""Deterministic synthetic-frame backend for TUI development and CI."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

from openbrightness.due.capture.base import (
    DisplayCaptureBackend,
    ErrorCallback,
    FrameCallback,
)
from openbrightness.due.models import DisplayFrame, OutputInfo

log = logging.getLogger(__name__)

ContentGenerator = Callable[[int, int, int], NDArray[np.uint8]]


def gradient_content(frame_index: int, width: int, height: int) -> NDArray[np.uint8]:
    """Horizontal gray ramp whose midpoint drifts with the frame index."""
    row = np.linspace(0, 255, width, dtype=np.uint8)
    drift = (frame_index * 8) % 256
    row = ((row.astype(np.int16) + drift) % 256).astype(np.uint8)
    plane = np.tile(row, (height, 1))
    return np.ascontiguousarray(np.stack([plane, plane, plane], axis=-1))


def checkerboard_content(frame_index: int, width: int, height: int) -> NDArray[np.uint8]:
    """Phase-shifting checkerboard; polarity flips each frame."""
    cell = 16
    ys, xs = np.mgrid[0:height, 0:width]
    offset = (frame_index // 2) % 2
    mask = (((ys // cell) + (xs // cell) + offset) % 2 == 0).astype(np.uint8) * 255
    return np.ascontiguousarray(np.stack([mask, mask, mask], axis=-1))


def sweep_content(frame_index: int, width: int, height: int) -> NDArray[np.uint8]:
    """Full-frame luminance sweep: 0 -> 255 and back over 64 frames."""
    period = 64
    phase = frame_index % (2 * period)
    value = phase if phase < period else 2 * period - phase
    return np.ascontiguousarray(
        np.full((height, width, 3), int(value * 255 / period), dtype=np.uint8)
    )


CONTENT_GENERATORS: dict[str, ContentGenerator] = {
    "gradient": gradient_content,
    "checkerboard": checkerboard_content,
    "sweep": sweep_content,
}


class MockCaptureBackend(DisplayCaptureBackend):
    """Generates synthetic frames at a fixed rate on a timer thread."""

    def __init__(
        self,
        output: OutputInfo,
        fps: float = 1.0,
        content: str = "gradient",
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        super().__init__(output)
        if fps <= 0:
            raise ValueError(f"fps must be > 0, got {fps}")
        if content not in CONTENT_GENERATORS:
            raise ValueError(f"unknown content {content!r}; choose from {sorted(CONTENT_GENERATORS)}")
        self._fps = fps
        self._content = CONTENT_GENERATORS[content]
        self._width = width or output.width
        self._height = height or output.height
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._frame_index = 0

    @property
    def name(self) -> str:
        return "mock"

    @property
    def frame_index(self) -> int:
        return self._frame_index

    def start(self, on_frame: FrameCallback, on_error: ErrorCallback | None = None) -> None:
        if self._thread is not None:
            raise RuntimeError("mock backend already started")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(on_frame, on_error),
            name="due-mock-capture",
            daemon=True,
        )
        self._thread.start()
        log.debug("mock backend started: %dx%d @ %.1f fps", self._width, self._height, self._fps)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        log.debug("mock backend stopped")

    def _run(self, on_frame: FrameCallback, on_error: ErrorCallback | None) -> None:
        interval = 1.0 / self._fps
        while not self._stop_event.is_set():
            started = time.monotonic()
            try:
                data = self._content(self._frame_index, self._width, self._height)
                frame = DisplayFrame(
                    data=data,
                    width=self._width,
                    height=self._height,
                    pts_ns=None,
                    captured_monotonic_ns=time.monotonic_ns(),
                )
                self._frame_index += 1
                on_frame(frame)
            except Exception as exc:
                log.exception("mock backend frame failure")
                if on_error is not None:
                    on_error(exc)
            elapsed = time.monotonic() - started
            self._stop_event.wait(max(interval - elapsed, 0.0))
