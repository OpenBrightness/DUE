"""LogindBacklightBackend tests (PLAN.md 11.5) — fake sysfs + fake D-Bus."""

from __future__ import annotations

from pathlib import Path

import pytest

from openbrightness.due.control.base import BacklightUnavailableError
from openbrightness.due.control.logind import (
    LogindBacklightBackend,
    discover_backlight_device,
)


def make_device(root: Path, name: str, type_: str, max_b: int, current: int) -> Path:
    dev = root / name
    dev.mkdir(parents=True)
    (dev / "type").write_text(type_)
    (dev / "max_brightness").write_text(str(max_b))
    (dev / "brightness").write_text(str(current))
    (dev / "actual_brightness").write_text(str(current))
    return dev


class RecordingBus:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str, tuple[object, ...]]] = []
        self.fail = False

    def __call__(self, dest, path, iface, method, args):
        if self.fail:
            raise RuntimeError("D-Bus error")
        self.calls.append((dest, path, iface, method, args))


def test_discovery_prefers_raw(tmp_path: Path) -> None:
    make_device(tmp_path, "acpi_video0", "firmware", 15, 10)
    make_device(tmp_path, "amdgpu_bl1", "raw", 65535, 32000)
    make_device(tmp_path, "vendor_bl", "platform", 100, 50)
    assert discover_backlight_device(tmp_path) == "amdgpu_bl1"


def test_discovery_platform_over_firmware(tmp_path: Path) -> None:
    make_device(tmp_path, "acpi_video0", "firmware", 15, 10)
    make_device(tmp_path, "vendor_bl", "platform", 100, 50)
    assert discover_backlight_device(tmp_path) == "vendor_bl"


def test_discovery_empty_raises(tmp_path: Path) -> None:
    with pytest.raises(BacklightUnavailableError):
        discover_backlight_device(tmp_path)


def test_normalized_get_brightness(tmp_path: Path) -> None:
    make_device(tmp_path, "amdgpu_bl1", "raw", 65535, 32768)
    bus = RecordingBus()
    backend = LogindBacklightBackend(root=tmp_path, dbus_call=bus, session_id="2")
    assert backend.max_brightness == 65535
    assert backend.get_brightness() == pytest.approx(32768 / 65535)


def test_get_prefers_setpoint_over_actual(tmp_path: Path) -> None:
    """amdgpu reports different scales in the two files (43528 vs 35185 live);
    reads must use the setpoint domain so drift detection matches our writes."""
    dev = make_device(tmp_path, "amdgpu_bl1", "raw", 65535, 43528)
    (dev / "actual_brightness").write_text("35185")
    backend = LogindBacklightBackend(root=tmp_path, dbus_call=RecordingBus())
    assert backend.get_brightness() == pytest.approx(43528 / 65535)


def test_set_brightness_call_shape(tmp_path: Path) -> None:
    make_device(tmp_path, "amdgpu_bl1", "raw", 65535, 100)
    bus = RecordingBus()
    backend = LogindBacklightBackend(root=tmp_path, dbus_call=bus, session_id="7")
    assert backend.set_brightness(0.5) is True
    assert len(bus.calls) == 1
    dest, path, iface, method, args = bus.calls[0]
    assert dest == "org.freedesktop.login1"
    assert path == "/org/freedesktop/login1/session/7"
    assert iface == "org.freedesktop.login1.Session"
    assert method == "SetBrightness"
    subtype, device, raw = args  # live-verified shape ("backlight", dev, u)
    assert subtype == "backlight"
    assert device == "amdgpu_bl1"
    assert raw == round(0.5 * 65535)


def test_set_brightness_clamps_range(tmp_path: Path) -> None:
    make_device(tmp_path, "amdgpu_bl1", "raw", 65535, 100)
    bus = RecordingBus()
    backend = LogindBacklightBackend(root=tmp_path, dbus_call=bus, session_id="2")
    backend.set_brightness(-0.5)
    backend.set_brightness(1.5)
    assert bus.calls[0][4][2] == 0
    assert bus.calls[1][4][2] == 65535


def test_dbus_failure_returns_false(tmp_path: Path) -> None:
    make_device(tmp_path, "amdgpu_bl1", "raw", 65535, 100)
    bus = RecordingBus()
    bus.fail = True
    backend = LogindBacklightBackend(root=tmp_path, dbus_call=bus, session_id="2")
    assert backend.set_brightness(0.5) is False


def test_sysfs_fallback_when_logind_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import openbrightness.due.control.logind as logind_mod

    dev = make_device(tmp_path, "amdgpu_bl1", "raw", 65535, 100)

    def boom(device: str, raw: int, session_id: str | None = None) -> None:
        raise RuntimeError("simulated logind failure")

    monkeypatch.setattr(logind_mod, "_logind_set_brightness", boom)
    backend = LogindBacklightBackend(root=tmp_path, dbus_call=None, session_id="2")
    assert backend.set_brightness(0.25) is True  # falls back to direct sysfs
    assert (dev / "brightness").read_text().strip() == str(round(0.25 * 65535))


def test_missing_session_uses_sysfs_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import openbrightness.due.control.logind as logind_mod

    dev = make_device(tmp_path, "amdgpu_bl1", "raw", 65535, 100)
    monkeypatch.delenv("XDG_SESSION_ID", raising=False)

    def boom(device: str, raw: int, session_id: str | None = None) -> None:
        raise RuntimeError("must never reach real logind in tests")

    monkeypatch.setattr(logind_mod, "_logind_set_brightness", boom)
    backend = LogindBacklightBackend(root=tmp_path, dbus_call=None)
    assert backend.set_brightness(0.5) is True
    assert (dev / "brightness").read_text().strip() == str(round(0.5 * 65535))


def test_describe_mentions_device(tmp_path: Path) -> None:
    make_device(tmp_path, "amdgpu_bl1", "raw", 65535, 100)
    backend = LogindBacklightBackend(root=tmp_path, dbus_call=RecordingBus())
    assert "amdgpu_bl1" in backend.describe()
    assert "65535" in backend.describe()
