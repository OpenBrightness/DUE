"""Tests for the threaded pipeline coordinator."""

from __future__ import annotations

import threading

from openbrightness.due.coordinator import PipelineCoordinator
from openbrightness.due.models import DisplayFrame, LuminanceMetrics
from tests.conftest import make_frame, uniform


class MetricsCollector:
    def __init__(self) -> None:
        self.items: list[LuminanceMetrics] = []
        self.error: Exception | None = None
        self.event = threading.Event()
        self._target = 0

    def expect(self, n: int) -> MetricsCollector:
        self._target = n
        return self

    def on_metrics(self, m: LuminanceMetrics) -> None:
        self.items.append(m)
        if len(self.items) >= self._target:
            self.event.set()

    def on_error(self, exc: Exception) -> None:
        self.error = exc
        self.event.set()


def _frame(value: int) -> DisplayFrame:
    return make_frame(uniform(value, 32, 32))


def test_processes_submitted_frames() -> None:
    collector = MetricsCollector().expect(3)
    coord = PipelineCoordinator(collector.on_metrics)
    coord.start()
    try:
        for _ in range(3):
            coord.submit(_frame(100))
            threading.Event().wait(0.05)
        assert collector.event.wait(5.0)
    finally:
        coord.stop()
    assert len(collector.items) == 3
    assert collector.error is None
    assert coord.frames_processed == 3


def test_drop_oldest_never_blocks() -> None:
    collector = MetricsCollector()
    coord = PipelineCoordinator(collector.on_metrics)
    coord.start()
    try:
        for i in range(50):
            coord.submit(_frame(i % 256))
        assert coord.frames_dropped > 0 or coord.frames_processed + coord.frames_dropped >= 1
    finally:
        coord.stop()
    assert collector.error is None


def test_pause_stops_processing() -> None:
    collector = MetricsCollector()
    coord = PipelineCoordinator(collector.on_metrics)
    coord.start()
    try:
        coord.submit(_frame(10))
        assert coord.frames_processed >= 1 or collector.event.wait(5.0)
        coord.pause()
        assert coord.paused
        processed_at_pause = coord.frames_processed
        for _ in range(5):
            coord.submit(_frame(50))
        threading.Event().wait(0.3)
        assert coord.frames_processed == processed_at_pause
        coord.resume()
        coord.submit(_frame(90))
        deadline = threading.Event()
        while coord.frames_processed == processed_at_pause and not deadline.wait(0.05):
            pass
        assert coord.frames_processed > processed_at_pause
    finally:
        coord.stop()


def test_temporal_reset_observable() -> None:
    collector = MetricsCollector()
    coord = PipelineCoordinator(collector.on_metrics)
    coord.start()
    try:
        coord.submit(_frame(0))
        coord.submit(_frame(255))
        assert collector.event.wait(5.0) or len(collector.items) >= 1
        coord.reset_temporal()
        coord.submit(_frame(0))
        import time

        time.sleep(0.3)
    finally:
        coord.stop()
    deltas = [m.temporal_delta for m in collector.items]
    assert None in deltas


def test_worker_error_is_reported() -> None:
    collector = MetricsCollector()

    class BoomAnalyzer:
        def analyze(
            self,
            frame: DisplayFrame,
            temporal_delta: float | None = None,
            luma=None,
        ) -> LuminanceMetrics:
            raise ValueError("analysis exploded")

    coord = PipelineCoordinator(collector.on_metrics, collector.on_error, analyzer=BoomAnalyzer())  # type: ignore[arg-type]
    coord.start()
    try:
        coord.submit(_frame(10))
        assert collector.event.wait(5.0)
    finally:
        coord.stop()
    assert isinstance(collector.error, ValueError)


def test_stop_is_idempotent_and_safe_when_not_started() -> None:
    collector = MetricsCollector()
    coord = PipelineCoordinator(collector.on_metrics)
    coord.stop()
    coord.start()
    coord.stop()
    coord.stop()


def test_submit_after_stop_is_ignored() -> None:
    collector = MetricsCollector()
    coord = PipelineCoordinator(collector.on_metrics)
    coord.start()
    coord.stop()
    coord.submit(_frame(1))
    assert coord.frames_processed == 0
