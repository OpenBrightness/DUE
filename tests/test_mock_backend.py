"""Tests for the synthetic capture backend."""

from __future__ import annotations

import threading

import numpy as np
import pytest

from openbrightness.due.capture.base import CaptureError, DisplayCaptureBackend
from openbrightness.due.capture.mock import (
    CONTENT_GENERATORS,
    MockCaptureBackend,
    checkerboard_content,
    gradient_content,
    sweep_content,
)
from openbrightness.due.models import DisplayFrame, OutputInfo

OUTPUT = OutputInfo("MOCK-1", "DUE", "Synthetic", 160, 120, 60.0)


def _collect(backend: MockCaptureBackend, count: int, timeout: float = 5.0) -> list[DisplayFrame]:
    frames: list[DisplayFrame] = []
    done = threading.Event()

    def on_frame(frame: DisplayFrame) -> None:
        frames.append(frame)
        if len(frames) >= count:
            done.set()

    backend.start(on_frame)
    assert done.wait(timeout), f"only received {len(frames)}/{count} frames"
    backend.stop()
    return frames


def test_mock_streams_frames_at_rate() -> None:
    backend = MockCaptureBackend(OUTPUT, fps=20.0, width=64, height=48)
    frames = _collect(backend, 3)
    assert len(frames) == 3
    assert all(isinstance(f, DisplayFrame) for f in frames)
    assert frames[0].data.shape == (48, 64, 3)
    assert frames[0].data.dtype == np.uint8


def test_mock_frames_are_owned_copies() -> None:
    backend = MockCaptureBackend(OUTPUT, fps=20.0, width=64, height=48)
    frames = _collect(backend, 2)
    assert frames[0].data.flags["C_CONTIGUOUS"]
    frames[0].data[0, 0, 0] = 200
    assert not np.array_equal(frames[0].data, frames[1].data) or frames[1].data[0, 0, 0] != 200


def test_mock_stop_is_idempotent() -> None:
    backend = MockCaptureBackend(OUTPUT, fps=50.0, width=8, height=8)
    _collect(backend, 1)
    backend.stop()
    backend.stop()


def test_mock_start_twice_raises() -> None:
    backend = MockCaptureBackend(OUTPUT, fps=50.0, width=8, height=8)
    backend.start(lambda f: None)
    try:
        with pytest.raises(RuntimeError, match="already started"):
            backend.start(lambda f: None)
    finally:
        backend.stop()


def test_mock_validation() -> None:
    with pytest.raises(ValueError, match="fps"):
        MockCaptureBackend(OUTPUT, fps=0)
    with pytest.raises(ValueError, match="content"):
        MockCaptureBackend(OUTPUT, content="nope")


def test_content_generators_shapes() -> None:
    for name, gen in CONTENT_GENERATORS.items():
        data = gen(3, 32, 16)
        assert data.shape == (16, 32, 3), name
        assert data.dtype == np.uint8, name
        assert data.flags["C_CONTIGUOUS"], name


def test_content_generators_vary_over_time() -> None:
    assert not np.array_equal(gradient_content(0, 32, 16), gradient_content(1, 32, 16))
    assert not np.array_equal(checkerboard_content(0, 32, 16), checkerboard_content(2, 32, 16))
    assert not np.array_equal(sweep_content(0, 32, 16), sweep_content(1, 32, 16))


def test_mock_error_callback() -> None:
    backend = MockCaptureBackend(OUTPUT, fps=50.0, width=8, height=8)
    errors: list[Exception] = []
    got = threading.Event()

    def on_frame(frame: DisplayFrame) -> None:
        raise RuntimeError("boom")

    def on_error(exc: Exception) -> None:
        errors.append(exc)
        got.set()

    backend.start(on_frame, on_error)
    assert got.wait(5.0)
    backend.stop()
    assert isinstance(errors[0], RuntimeError)


def test_mock_is_backend_subclass() -> None:
    assert issubclass(MockCaptureBackend, DisplayCaptureBackend)
    assert issubclass(CaptureError, RuntimeError)
    backend = MockCaptureBackend(OUTPUT, fps=1.0, width=8, height=8)
    assert backend.name == "mock"
    assert backend.output is OUTPUT
