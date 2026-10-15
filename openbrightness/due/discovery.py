"""Active output enumeration (PLAN.md section 2.2).

Providers, in order:
1. ``niri msg -j outputs`` — Niri IPC (reference target).
2. ``org.gnome.Mutter.DisplayConfig`` over the session bus — works on any
   Mutter-based session (including Niri's internal Mutter bridge).
The parsing is provider-independent so tests can inject fixture payloads.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any

from openbrightness.due.models import OutputInfo

log = logging.getLogger(__name__)


class DiscoveryError(RuntimeError):
    """No provider could enumerate the active outputs."""


def _parse_niri_outputs(payload: list[dict[str, Any]]) -> list[OutputInfo]:
    outputs: list[OutputInfo] = []
    for entry in payload:
        if not entry.get("v1", {}).get("connected", True):
            continue
        v1 = entry.get("v1", {})
        mode = v1.get("mode") or {}
        width = int(mode.get("width") or v1.get("width") or 0)
        height = int(mode.get("height") or v1.get("height") or 0)
        if width <= 0 or height <= 0:
            continue
        refresh = float(mode.get("refresh_rate", 0) or 0) / 1000.0
        if refresh <= 0:
            refresh = float(v1.get("refresh_rate", 60000) or 60000) / 1000.0
        outputs.append(
            OutputInfo(
                connector=str(v1.get("name") or entry.get("name") or "unknown"),
                make=str(v1.get("make") or ""),
                model=str(v1.get("model") or ""),
                width=width,
                height=height,
                refresh_rate=refresh,
                is_primary=bool(v1.get("is_primary", False)),
            )
        )
    return outputs


def _parse_mutter_display_config(state: tuple[Any, ...]) -> list[OutputInfo]:
    """Parse ``GetCurrentState()`` from org.gnome.Mutter.DisplayConfig.

    Reply shape (verified live on niri):
    ``(serial, monitors, logical_monitors, properties)`` where
    - monitor entry: ``((connector, vendor, product, serial), modes, props)`` and
      mode entry: ``(id, width, height, refresh_hz, scale, scales, props)``;
    - logical monitor entry:
      ``(x, y, scale, transform, primary, [monitor_ids], props)``.
    """
    _serial, monitors, logical_monitors, _props = state

    specs: dict[str, tuple[str, str, int, int, float]] = {}
    for entry in monitors:
        monitor_id, modes, _mon_props = entry
        connector, vendor, product, _serial_no = monitor_id
        width, height, refresh = 0, 0, 60.0
        for mode in modes:
            _mode_id, m_w, m_h, m_refresh, _scale, _scales, mode_props = mode
            if mode_props.get("is-preferred") or width <= 0:
                width, height, refresh = int(m_w), int(m_h), float(m_refresh)
                if mode_props.get("is-preferred"):
                    break
        if width > 0:
            specs[str(connector)] = (str(vendor), str(product), width, height, refresh)

    primary_connectors: set[str] = set()
    for lm in logical_monitors:
        if bool(lm[4]):
            for monitor_id in lm[5]:
                primary_connectors.add(str(monitor_id[0]))

    outputs: list[OutputInfo] = []
    for connector, (vendor, product, width, height, refresh) in specs.items():
        outputs.append(
            OutputInfo(
                connector=connector,
                make=vendor,
                model=product,
                width=width,
                height=height,
                refresh_rate=refresh,
                is_primary=connector in primary_connectors,
            )
        )
    return outputs


def _probe_niri() -> list[OutputInfo] | None:
    if shutil.which("niri") is None:
        return None
    try:
        result = subprocess.run(
            ["niri", "msg", "-j", "outputs"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        log.debug("niri outputs probe failed: %s", exc)
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        log.debug("niri outputs JSON invalid: %s", exc)
        return None
    if not isinstance(payload, list):
        return None
    return _parse_niri_outputs(payload)


def _probe_mutter() -> list[OutputInfo] | None:
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
    except (ImportError, ValueError) as exc:
        log.debug("Gio unavailable for DisplayConfig probe: %s", exc)
        return None

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync(
            "org.gnome.Mutter.DisplayConfig",
            "/org/gnome/Mutter/DisplayConfig",
            "org.gnome.Mutter.DisplayConfig",
            "GetCurrentState",
            None,
            None,
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        )
    except Exception as exc:  # noqa: BLE001 — probe must fall through on any D-Bus failure
        log.debug("DisplayConfig probe failed: %s", exc)
        return None

    state = reply.unpack()
    if not isinstance(state, tuple) or len(state) < 4:
        return None
    return _parse_mutter_display_config(state)


def list_outputs() -> list[OutputInfo]:
    """Enumerate active outputs, preferring Niri IPC then Mutter DisplayConfig."""
    for probe in (_probe_niri, _probe_mutter):
        outputs = probe()
        if outputs:
            outputs.sort(key=lambda o: (not o.is_primary, o.connector))
            return outputs
    raise DiscoveryError(
        "no active outputs found (niri IPC and Mutter DisplayConfig both unavailable)"
    )


def find_output(connector: str, outputs: list[OutputInfo]) -> OutputInfo | None:
    """Look up an output by connector name, case-insensitively."""
    lowered = connector.lower()
    for output in outputs:
        if output.connector.lower() == lowered:
            return output
    return None
