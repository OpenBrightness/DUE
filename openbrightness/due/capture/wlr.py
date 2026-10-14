"""Live capture via zwlr_screencopy_manager_v1 + wl_shm (PLAN_V1.md M4).

Primary live backend on wlroots-family compositors (niri verified). Frames are
copied compositor-side into a shared-memory buffer we own, so pixel data is
plain CPU memory: no DMA-BUF import, no mapping tricks (see PLAN_V1.md section
2.1 for why the GStreamer/PipeWire path is not used on this stack).

The compositor connection is owned by one thread; ``on_frame`` runs on that
thread and must be fast (the coordinator's drop-oldest queue absorbs jitter).
"""

from __future__ import annotations

import contextlib
import logging
import mmap
import os
import threading
import time
from collections.abc import Buffer
from typing import Any

import numpy as np
from numpy.typing import NDArray

from openbrightness.due.capture.base import (
    CaptureError,
    DisplayCaptureBackend,
    DisplayDisconnectedError,
    ErrorCallback,
    FrameCallback,
)
from openbrightness.due.models import DisplayFrame, OutputInfo

log = logging.getLogger(__name__)

WL_SHM_FORMAT_ARGB8888 = 0
WL_SHM_FORMAT_XRGB8888 = 1
_FRAME_FLAG_Y_INVERT = 1
_BPP = 4
_MAX_COPY_POLLS = 1000


def bgrx_to_rgb(
    mm: Buffer, width: int, height: int, stride: int, y_invert: bool
) -> NDArray[np.uint8]:
    """Copy a BGRx/ARGBx shm frame into an owned RGB array.

    Handles padded stride and y-inversion; the result is C-contiguous so the
    shm mapping can be recycled immediately. Channel swap uses plain slice
    assignments (fancy-index reversal benchmarks ~6x slower on full frames).
    """
    rows = np.frombuffer(mm, dtype=np.uint8, count=stride * height).reshape(height, stride)
    bgrx = rows[:, : width * _BPP].reshape(height, width, _BPP)
    rgb = np.empty((height, width, 3), dtype=np.uint8)
    rgb[:, :, 0] = bgrx[:, :, 2]
    rgb[:, :, 1] = bgrx[:, :, 1]
    rgb[:, :, 2] = bgrx[:, :, 0]
    if y_invert:
        rgb = np.ascontiguousarray(rgb[::-1])
    return rgb


def match_output(
    outputs: dict[str, dict[str, Any]], connector: str, info: OutputInfo
) -> str | None:
    """Pick the wl_output global name for a connector.

    Name matching is authoritative when any output advertises a name (wl_output
    v4+); the size fallback only applies when the compositor provides no names.
    """
    if connector in outputs:
        return connector
    for name, data in outputs.items():
        if data.get("name") == connector:
            return name
    if any(data.get("name") for data in outputs.values()):
        return None
    for name, data in outputs.items():
        if data.get("size") == (info.width, info.height):
            return name
    return None


class WlrScreencopyBackend(DisplayCaptureBackend):
    """Pull-based capture: one compositor copy per frame at a fixed rate."""

    def __init__(self, output: OutputInfo, fps: float = 1.0) -> None:
        super().__init__(output)
        if fps <= 0:
            raise ValueError(f"fps must be > 0, got {fps}")
        self._fps = fps
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._frames_captured = 0

    @property
    def name(self) -> str:
        return "wlr"

    @property
    def frames_captured(self) -> int:
        return self._frames_captured

    def start(self, on_frame: FrameCallback, on_error: ErrorCallback | None = None) -> None:
        if self._thread is not None:
            raise RuntimeError("wlr backend already started")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(on_frame, on_error),
            name="due-wlr-capture",
            daemon=True,
        )
        self._thread.start()
        log.debug("wlr backend started: %s @ %.1f fps", self.output.connector, self._fps)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        log.debug("wlr backend stopped")

    def _run(self, on_frame: FrameCallback, on_error: ErrorCallback | None) -> None:
        try:
            self._loop(on_frame)
        except Exception as exc:
            log.exception("wlr capture thread failed")
            if on_error is not None:
                on_error(exc)

    def _loop(self, on_frame: FrameCallback) -> None:
        from pywayland.client.display import Display

        from openbrightness.due._proto.wayland import WlOutput, WlShm
        from openbrightness.due._proto.wlr_screencopy_unstable_v1 import (
            ZwlrScreencopyManagerV1,
        )

        display = Display()
        try:
            display.connect()
        except Exception as exc:
            raise CaptureError(f"could not connect to Wayland display: {exc}") from exc

        globals_found: dict[str, tuple[int, int]] = {}
        outputs: dict[str, dict[str, Any]] = {}

        def on_global(reg: Any, name: int, interface: str, version: int) -> None:
            globals_found[interface] = (name, version)
            if interface == "wl_output":
                out = reg.bind(name, WlOutput, min(version, 4))
                data: dict[str, Any] = {"global": name, "proxy": out}
                outputs[str(name)] = data

                def on_geometry(_obj: object, *args: Any, _d: dict[str, Any] = data) -> None:
                    _d["geometry"] = args

                def on_mode(_obj: object, *args: Any, _d: dict[str, Any] = data) -> None:
                    flags, w, h, _refresh = args
                    if flags & 1:
                        _d["size"] = (int(w), int(h))

                def on_name(_obj: object, *args: Any, _d: dict[str, Any] = data) -> None:
                    _d["name"] = str(args[0])

                out.dispatcher["geometry"] = on_geometry
                out.dispatcher["mode"] = on_mode
                out.dispatcher["name"] = on_name

        registry = display.get_registry()
        registry.dispatcher["global"] = on_global

        manager = None
        shm = None
        shm_state: dict[str, Any] = {}
        outputs_state = outputs
        try:
            display.roundtrip()
            display.roundtrip()

            if "zwlr_screencopy_manager_v1" not in globals_found:
                raise CaptureError("compositor lacks zwlr_screencopy_manager_v1")
            if "wl_shm" not in globals_found:
                raise CaptureError("compositor lacks wl_shm")

            target = match_output(outputs, self.output.connector, self.output)
            if target is None:
                available = [str(d.get("name") or n) for n, d in outputs.items()]
                raise CaptureError(
                    f"output {self.output.connector!r} not found; available: {available}"
                )

            shm = registry.bind(globals_found["wl_shm"][0], WlShm, 1)
            manager = registry.bind(
                globals_found["zwlr_screencopy_manager_v1"][0], ZwlrScreencopyManagerV1, 1
            )
            display.roundtrip()

            interval = 1.0 / self._fps
            consecutive_failures = 0

            while not self._stop_event.is_set():
                started = time.monotonic()
                frame = self._capture_once(display, manager, shm, outputs[target], shm_state)
                if frame is not None:
                    consecutive_failures = 0
                    self._frames_captured += 1
                    on_frame(frame)
                else:
                    consecutive_failures += 1
                    if consecutive_failures >= 5:
                        raise DisplayDisconnectedError(
                            f"capture of {self.output.connector} failed repeatedly "
                            "(display disconnected or session locked?)"
                        )
                elapsed = time.monotonic() - started
                self._stop_event.wait(max(interval - elapsed, 0.0))
        finally:
            self._teardown(shm_state)
            for proxy in (manager, shm):
                if proxy is not None:
                    with contextlib.suppress(Exception):
                        proxy.destroy()
            with contextlib.suppress(Exception):
                registry.destroy()
            for data in outputs_state.values():
                with contextlib.suppress(Exception):
                    data["proxy"].destroy()
            with contextlib.suppress(Exception):
                display.disconnect()

    def _capture_once(
        self,
        display: Any,
        manager: Any,
        shm: Any,
        output_data: dict[str, Any],
        shm_state: dict[str, Any],
    ) -> DisplayFrame | None:
        state: dict[str, Any] = {"done": False, "failed": False}

        def on_buffer(_obj: object, fmt: int, w: int, h: int, stride: int) -> None:
            state.update(fmt=fmt, width=w, height=h, stride=stride)

        def on_flags(_obj: object, *args: Any) -> None:
            state["flags"] = args[0]

        def on_ready(_obj: object, *args: Any) -> None:
            state["done"] = True
            if len(args) == 3:
                state["pts_ns"] = (int(args[0]) << 32 | int(args[1])) * 1_000_000_000 + int(args[2])

        def on_failed(_obj: object, *args: object) -> None:
            state["failed"] = True

        out = output_data["proxy"]
        frame = manager.capture_output(0, out)
        frame.dispatcher["buffer"] = on_buffer
        frame.dispatcher["flags"] = on_flags
        frame.dispatcher["ready"] = on_ready
        frame.dispatcher["failed"] = on_failed

        try:
            display.roundtrip()
            if state["failed"] or "width" not in state:
                return None

            width = int(state["width"])
            height = int(state["height"])
            stride = int(state["stride"])
            fmt = int(state["fmt"])
            if fmt not in (WL_SHM_FORMAT_ARGB8888, WL_SHM_FORMAT_XRGB8888):
                raise CaptureError(f"unsupported wl_shm format {fmt}")

            _pool, buf, mm = self._ensure_shm(shm, shm_state, width, height, stride, fmt)
            frame.copy(buf)

            polls = 0
            while not state["done"] and not state["failed"] and polls < _MAX_COPY_POLLS:
                display.roundtrip()
                polls += 1
            if state["failed"] or not state["done"]:
                return None

            rgb = bgrx_to_rgb(
                mm, width, height, stride, bool(int(state.get("flags", 0)) & _FRAME_FLAG_Y_INVERT)
            )
            return DisplayFrame(
                data=rgb,
                width=width,
                height=height,
                pts_ns=state.get("pts_ns"),
                captured_monotonic_ns=time.monotonic_ns(),
            )
        finally:
            with contextlib.suppress(Exception):
                frame.destroy()

    def _ensure_shm(
        self,
        shm: Any,
        shm_state: dict[str, Any],
        width: int,
        height: int,
        stride: int,
        fmt: int,
    ) -> tuple[Any, Any, mmap.mmap]:
        if shm_state.get("dims") != (width, height, stride, fmt):
            self._teardown(shm_state)
            size = stride * height
            fd = os.memfd_create("due-frame", 0)
            os.ftruncate(fd, size)
            mm = mmap.mmap(fd, size)
            pool = shm.create_pool(fd, size)
            buf = pool.create_buffer(0, width, height, stride, fmt)
            os.close(fd)
            shm_state.update(dims=(width, height, stride, fmt), pool=pool, buf=buf, mm=mm)
        return shm_state["pool"], shm_state["buf"], shm_state["mm"]

    def _teardown(self, shm_state: dict[str, Any]) -> None:
        for key in ("buf", "pool"):
            proxy = shm_state.pop(key, None)
            if proxy is not None:
                with contextlib.suppress(Exception):
                    proxy.destroy()
        mm = shm_state.pop("mm", None)
        shm_state.pop("dims", None)
        if mm is not None:
            with contextlib.suppress(Exception):
                mm.close()
