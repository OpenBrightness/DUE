"""Live capture integration test — auto-skips without a Wayland session.

Manual checklist (PLAN_V1.md M6):
- capture frames at the expected physical resolution
- y-inversion and stride handled correctly (visual sanity via mean values)
- clean teardown with no leaked shm pools
"""

from __future__ import annotations

import os
import threading

import pytest

from openbrightness.due.capture.base import CaptureError
from openbrightness.due.capture.wlr import WlrScreencopyBackend
from openbrightness.due.models import OutputInfo

pytestmark = pytest.mark.skipif(
    not os.environ.get("WAYLAND_DISPLAY"),
    reason="no Wayland session available",
)


def _first_output() -> OutputInfo | None:
    from openbrightness.due.discovery import DiscoveryError, list_outputs

    try:
        outputs = list_outputs()
    except DiscoveryError:
        return None
    return outputs[0] if outputs else None


def test_live_capture_real_frames() -> None:
    output = _first_output()
    if output is None:
        pytest.skip("no outputs discovered")

    frames = []
    errors = []
    got = threading.Event()

    def on_frame(frame):
        frames.append(frame)
        if len(frames) >= 2:
            got.set()

    def on_error(exc):
        errors.append(exc)
        got.set()

    backend = WlrScreencopyBackend(output, fps=4.0)
    backend.start(on_frame, on_error)
    try:
        assert got.wait(10.0), "no frames within 10s"
    finally:
        backend.stop()

    assert not errors, f"capture errors: {errors}"
    assert len(frames) >= 2
    frame = frames[0]
    assert frame.data.shape == (output.height, output.width, 3)
    assert frame.data.dtype.name == "uint8"
    assert frame.data.flags["C_CONTIGUOUS"]


def test_live_capture_missing_connector_errors() -> None:
    output = _first_output()
    if output is None:
        pytest.skip("no outputs discovered")

    bogus = OutputInfo("DUE-MISSING-1", "", "", output.width, output.height, 60.0)
    errors = []
    done = threading.Event()

    backend = WlrScreencopyBackend(bogus, fps=4.0)
    backend.start(lambda f: None, lambda e: (errors.append(e), done.set()))
    try:
        assert done.wait(10.0), "expected an error for missing connector"
    finally:
        backend.stop()
    assert isinstance(errors[0], CaptureError)
    assert "not found" in str(errors[0])
