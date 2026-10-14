"""Thread-safe pipeline orchestrator (PLAN_V1.md section 5).

Capture callbacks (GLib loop / timer thread) hand frames to a 1-slot
drop-oldest queue; a worker thread runs analysis + temporal tracking and
emits :class:`LuminanceMetrics` to a UI-facing callback. The worker never
touches UI objects directly — the callback posts messages.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable

from openbrightness.due.analysis.luminance import LuminanceAnalyzer, frame_luma
from openbrightness.due.models import DisplayFrame, LuminanceMetrics
from openbrightness.due.temporal.tracker import TemporalTracker

log = logging.getLogger(__name__)

MetricsCallback = Callable[[LuminanceMetrics], None]
ErrorCallback = Callable[[Exception], None]

_SENTINEL = object()


class PipelineCoordinator:
    """Owns the frame queue, worker thread, analyzer, and temporal tracker."""

    def __init__(
        self,
        on_metrics: MetricsCallback,
        on_error: ErrorCallback | None = None,
        analyzer: LuminanceAnalyzer | None = None,
        tracker: TemporalTracker | None = None,
    ) -> None:
        self._on_metrics = on_metrics
        self._on_error = on_error
        self._analyzer = analyzer or LuminanceAnalyzer()
        self._tracker = tracker or TemporalTracker()
        self._queue: queue.Queue[DisplayFrame | object] = queue.Queue(maxsize=1)
        self._worker: threading.Thread | None = None
        self._running = threading.Event()
        self._paused = threading.Event()
        self._frames_dropped = 0
        self._frames_processed = 0

    @property
    def frames_processed(self) -> int:
        return self._frames_processed

    @property
    def frames_dropped(self) -> int:
        return self._frames_dropped

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def start(self) -> None:
        if self._worker is not None:
            raise RuntimeError("coordinator already started")
        self._running.set()
        self._paused.clear()
        self._worker = threading.Thread(
            target=self._run, name="due-analysis-worker", daemon=True
        )
        self._worker.start()
        log.debug("coordinator started")

    def stop(self, timeout: float = 2.0) -> None:
        self._running.clear()
        self._drain()
        try:
            self._queue.put_nowait(_SENTINEL)
        except queue.Full:
            pass
        if self._worker is not None:
            self._worker.join(timeout=timeout)
            self._worker = None
        self._drain()
        log.debug("coordinator stopped")

    def submit(self, frame: DisplayFrame) -> None:
        """Called from the capture thread. Never blocks; drops oldest on full."""
        if not self._running.is_set():
            return
        while True:
            try:
                self._queue.put_nowait(frame)
                return
            except queue.Full:
                try:
                    self._queue.get_nowait()
                    self._frames_dropped += 1
                except queue.Empty:
                    pass

    def pause(self) -> None:
        self._paused.set()
        self._drain()
        log.debug("coordinator paused")

    def resume(self) -> None:
        self._paused.clear()
        log.debug("coordinator resumed")

    def reset_temporal(self) -> None:
        self._tracker.reset()
        log.debug("temporal state reset")

    def _drain(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def _run(self) -> None:
        while self._running.is_set():
            try:
                item = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if item is _SENTINEL:
                return
            if self._paused.is_set():
                continue
            frame = item
            assert isinstance(frame, DisplayFrame)
            try:
                y, _sub_w, _sub_h = frame_luma(frame)
                delta = self._tracker.update(frame, luma=y)
                metrics = self._analyzer.analyze(frame, temporal_delta=delta, luma=y)
                self._frames_processed += 1
                self._on_metrics(metrics)
            except Exception as exc:
                log.exception("analysis worker failure")
                if self._on_error is not None:
                    self._on_error(exc)
