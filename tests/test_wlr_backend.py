"""Tests for the wlr screencopy backend's pure logic (no compositor needed)."""

from __future__ import annotations

import mmap
import os

import pytest

from openbrightness.due.capture.base import DisplayCaptureBackend
from openbrightness.due.capture.wlr import WlrScreencopyBackend, bgrx_to_rgb, match_output
from openbrightness.due.models import OutputInfo

OUTPUT = OutputInfo("eDP-1", "BOE", "X", 1920, 1200, 60.0)


def _shm(size: int) -> mmap.mmap:
    fd = os.memfd_create("due-test", 0)
    os.ftruncate(fd, size)
    mm = mmap.mmap(fd, size)
    os.close(fd)
    return mm


def test_bgrx_to_rgb_basic() -> None:
    w, h, stride = 2, 2, 8
    mm = _shm(stride * h)
    # pixel (0,0) = B,G,R,X = 10,20,30,0 -> RGB 30,20,10
    mm[0:4] = bytes([10, 20, 30, 0])
    mm[4:8] = bytes([1, 2, 3, 0])
    mm[8:12] = bytes([40, 50, 60, 0])
    mm[12:16] = bytes([4, 5, 6, 0])
    rgb = bgrx_to_rgb(mm, w, h, stride, y_invert=False)
    assert rgb.shape == (2, 2, 3)
    assert list(rgb[0, 0]) == [30, 20, 10]
    assert list(rgb[0, 1]) == [3, 2, 1]
    assert list(rgb[1, 0]) == [60, 50, 40]
    assert rgb.flags["C_CONTIGUOUS"]
    mm.close()


def test_bgrx_to_rgb_padded_stride() -> None:
    w, h, stride = 2, 2, 16  # 8 bytes padding per row
    mm = _shm(stride * h)
    mm[0:4] = bytes([10, 20, 30, 0])
    mm[4:8] = bytes([1, 2, 3, 0])
    mm[8:16] = b"\xff" * 8  # padding garbage
    mm[16:20] = bytes([40, 50, 60, 0])
    mm[20:24] = bytes([4, 5, 6, 0])
    rgb = bgrx_to_rgb(mm, w, h, stride, y_invert=False)
    assert list(rgb[0, 0]) == [30, 20, 10]
    assert list(rgb[1, 0]) == [60, 50, 40]
    mm.close()


def test_bgrx_to_rgb_y_invert() -> None:
    w, h, stride = 1, 2, 4
    mm = _shm(stride * h)
    mm[0:4] = bytes([10, 20, 30, 0])  # row 0
    mm[4:8] = bytes([40, 50, 60, 0])  # row 1
    rgb = bgrx_to_rgb(mm, w, h, stride, y_invert=True)
    assert list(rgb[0, 0]) == [60, 50, 40]
    assert list(rgb[1, 0]) == [30, 20, 10]
    mm.close()


def test_match_output_by_name() -> None:
    outputs = {
        "44": {"name": "eDP-1", "size": (1920, 1200), "proxy": object()},
        "50": {"name": "HDMI-A-1", "size": (1920, 1080), "proxy": object()},
    }
    assert match_output(outputs, "HDMI-A-1", OUTPUT) == "50"


def test_match_output_by_size_fallback() -> None:
    outputs = {"44": {"size": (1920, 1200), "proxy": object()}}
    assert match_output(outputs, "eDP-1", OUTPUT) == "44"


def test_match_output_missing() -> None:
    outputs = {"44": {"name": "DP-9", "size": (100, 100), "proxy": object()}}
    assert match_output(outputs, "eDP-1", OUTPUT) is None


def test_backend_validation_and_identity() -> None:
    assert issubclass(WlrScreencopyBackend, DisplayCaptureBackend)
    with pytest.raises(ValueError, match="fps"):
        WlrScreencopyBackend(OUTPUT, fps=0)
    backend = WlrScreencopyBackend(OUTPUT, fps=1.0)
    assert backend.name == "wlr"
    assert backend.output is OUTPUT
    backend.stop()


def test_start_twice_raises() -> None:
    import threading

    backend = WlrScreencopyBackend(OUTPUT, fps=1.0)
    started = threading.Event()

    def on_frame(f):
        pass

    backend._thread = threading.Thread(target=started.wait, daemon=True)
    backend._thread.start()
    try:
        with pytest.raises(RuntimeError, match="already started"):
            backend.start(on_frame)
    finally:
        backend._stop_event.set()
        backend._thread.join(timeout=2)
        backend._thread = None
