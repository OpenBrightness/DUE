"""Internal-panel backlight control via sysfs + systemd-logind.

Research report section 2: on this hardware the panel is
``/sys/class/backlight/amdgpu_bl1`` (type ``raw``, 65535 steps, non-linear
scale). Direct sysfs writes need root, but any active session can call
``org.freedesktop.login1.Session.SetBrightness("backlight", <dev>, u)`` —
verified live on session 2. A direct sysfs write is kept as fallback for
setups with udev ``uaccess`` grants.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

from openbrightness.due.control.base import (
    BacklightUnavailableError,
    ControlWriteError,
    DisplayControlBackend,
)

log = logging.getLogger(__name__)

_TYPE_PRECEDENCE = {"raw": 0, "platform": 1, "firmware": 2}
_DEFAULT_MAX = 65535
LOGIN_DEST = "org.freedesktop.login1"
LOGIN_SESSION_IFACE = "org.freedesktop.login1.Session"

# Signature: (bus_name, object_path, interface, method, args) -> None (raises on error)
DBusCall = Callable[[str, str, str, str, tuple[object, ...]], None]


def discover_backlight_device(root: str | Path = "/sys/class/backlight") -> str:
    """Pick the backlight device name using raw > platform > firmware.

    Mirrors the kernel/systemd selection policy (research 2.2). Raises
    ``BacklightUnavailableError`` when no device exists.
    """
    root_path = Path(root)
    candidates: list[tuple[int, str]] = []
    if root_path.is_dir():
        for entry in root_path.iterdir():
            type_file = entry / "type"
            if not (entry.is_dir() and type_file.is_file()):
                continue
            try:
                device_type = type_file.read_text().strip().lower()
            except OSError:
                continue
            candidates.append((_TYPE_PRECEDENCE.get(device_type, 3), entry.name))
    if not candidates:
        raise BacklightUnavailableError(f"no backlight device under {root_path}")
    candidates.sort()
    return candidates[0][1]


def _session_object_path(session_id: str | None = None) -> str:
    session = session_id or os.environ.get("XDG_SESSION_ID", "")
    if not session:
        raise ControlWriteError("XDG_SESSION_ID is not set; cannot reach logind session")
    return f"/org/freedesktop/login1/session/{session}"


def _logind_set_brightness(
    device: str, raw_value: int, session_id: str | None = None
) -> None:
    """Write via systemd-logind on the system bus (research 2.3, path 1)."""
    import gi

    gi.require_version("Gio", "2.0")
    gi.require_version("GLib", "2.0")
    from gi.repository import Gio, GLib

    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    bus.call_sync(
        LOGIN_DEST,
        _session_object_path(session_id),
        LOGIN_SESSION_IFACE,
        "SetBrightness",
        GLib.Variant("(ssu)", ("backlight", device, raw_value)),
        None,
        Gio.DBusCallFlags.NONE,
        2000,
        None,
    )


class LogindBacklightBackend(DisplayControlBackend):
    """Brightness control for the laptop internal panel.

    ``dbus_call`` and ``root`` are injectable for tests; production uses
    ``logind_set_brightness`` against ``/sys/class/backlight``.
    """

    def __init__(
        self,
        device: str | None = None,
        root: str | Path = "/sys/class/backlight",
        dbus_call: DBusCall | None = None,
        session_id: str | None = None,
    ) -> None:
        self._root = Path(root)
        self._device = device or discover_backlight_device(self._root)
        self._dbus_call = dbus_call
        self._session_id = session_id
        device_dir = self._root / self._device
        self._max_brightness = self._read_int(device_dir / "max_brightness") or _DEFAULT_MAX
        self._device_dir = device_dir

    def _read_int(self, path: Path) -> int | None:
        try:
            return int(path.read_text().strip())
        except (OSError, ValueError):
            return None

    @property
    def device(self) -> str:
        return self._device

    @property
    def max_brightness(self) -> int:
        return self._max_brightness

    def get_brightness(self) -> float | None:
        current = self._read_int(self._device_dir / "actual_brightness")
        if current is None:
            current = self._read_int(self._device_dir / "brightness")
        if current is None:
            return None
        return max(0.0, min(1.0, current / self._max_brightness))

    def set_brightness(self, value: float) -> bool:
        raw = round(max(0.0, min(1.0, value)) * self._max_brightness)
        try:
            self._write(raw)
        except Exception as exc:  # noqa: BLE001 — ABC contract: degrade, never raise
            log.debug("brightness write failed for %s: %s", self._device, exc)
            return False
        return True

    def _write(self, raw: int) -> None:
        if self._dbus_call is not None:
            self._dbus_call(
                LOGIN_DEST,
                _session_object_path(self._session_id),
                LOGIN_SESSION_IFACE,
                "SetBrightness",
                ("backlight", self._device, raw),
            )
            return
        try:
            _logind_set_brightness(self._device, raw, self._session_id)
        except Exception as exc:  # noqa: BLE001 — any logind failure triggers fallback
            log.debug("logind SetBrightness failed (%s); trying direct sysfs", exc)
            try:
                (self._device_dir / "brightness").write_text(str(raw))
            except OSError as io_exc:
                raise ControlWriteError(
                    f"neither logind nor direct write worked for {self._device}"
                ) from io_exc

    def describe(self) -> str:
        return f"logind backlight {self._device} (max {self._max_brightness})"
