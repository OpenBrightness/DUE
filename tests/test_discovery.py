"""Tests for output enumeration and parsing."""

from __future__ import annotations

from typing import Any

import pytest

from openbrightness.due.discovery import (
    DiscoveryError,
    _parse_mutter_display_config,
    _parse_niri_outputs,
    find_output,
    list_outputs,
)

NIRI_FIXTURE: list[dict[str, Any]] = [
    {
        "name": "eDP-1",
        "v1": {
            "name": "eDP-1",
            "make": "BOE",
            "model": "NE160QDM-NY1",
            "connected": True,
            "is_primary": True,
            "mode": {"width": 1920, "height": 1200, "refresh_rate": 60010},
        },
    },
    {
        "name": "HDMI-A-1",
        "v1": {
            "name": "HDMI-A-1",
            "make": "LG",
            "model": "27GN800",
            "connected": True,
            "is_primary": False,
            "mode": {"width": 2560, "height": 1440, "refresh_rate": 143998},
        },
    },
    {
        "name": "DP-2",
        "v1": {"name": "DP-2", "connected": False},
    },
]


def test_parse_niri_outputs() -> None:
    outputs = _parse_niri_outputs(NIRI_FIXTURE)
    assert [o.connector for o in outputs] == ["eDP-1", "HDMI-A-1"]
    primary = outputs[0]
    assert primary.is_primary is True
    assert primary.width == 1920
    assert primary.height == 1200
    assert primary.refresh_rate == pytest.approx(60.010)
    assert primary.label == "eDP-1 (BOE NE160QDM-NY1)"


def test_parse_niri_skips_disconnected_and_bad_modes() -> None:
    fixture = NIRI_FIXTURE + [
        {"name": "DP-3", "v1": {"name": "DP-3", "connected": True, "mode": None}},
    ]
    outputs = _parse_niri_outputs(fixture)
    assert "DP-2" not in [o.connector for o in outputs]
    assert "DP-3" not in [o.connector for o in outputs]


def test_parse_mutter_display_config() -> None:
    # Live-verified GetCurrentState shape:
    # (serial, monitors, logical_monitors, properties)
    state = (
        42,
        [
            (
                ("eDP-1", "BOE", "0x1234", "serial1"),
                [
                    ("a", 1920, 1200, 60.0, 1.0, [1.0], {"is-preferred": True}),
                    ("b", 1920, 1200, 120.0, 1.0, [1.0], {}),
                ],
                {},
            ),
            (
                ("HDMI-A-1", "LG", "0x5678", "serial2"),
                [("c", 2560, 1440, 144.0, 1.0, [1.0], {"is-preferred": True})],
                {},
            ),
        ],
        [
            (0, 0, 1.0, 0, True, [("eDP-1", "BOE", "0x1234", "serial1")], {}),
            (1920, 0, 1.0, 0, False, [("HDMI-A-1", "LG", "0x5678", "serial2")], {}),
        ],
        {"layout-mode": 1},
    )
    outputs = _parse_mutter_display_config(state)
    assert sorted(o.connector for o in outputs) == ["HDMI-A-1", "eDP-1"]
    by_name = {o.connector: o for o in outputs}
    assert by_name["eDP-1"].is_primary is True
    assert by_name["eDP-1"].width == 1920
    assert by_name["eDP-1"].refresh_rate == pytest.approx(60.0)
    assert by_name["HDMI-A-1"].is_primary is False
    assert by_name["HDMI-A-1"].refresh_rate == pytest.approx(144.0)


def test_find_output_case_insensitive() -> None:
    outputs = _parse_niri_outputs(NIRI_FIXTURE)
    assert find_output("edp-1", outputs) is outputs[0]
    assert find_output("DP-9", outputs) is None


def test_list_outputs_raises_without_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("openbrightness.due.discovery._probe_niri", lambda: None)
    monkeypatch.setattr("openbrightness.due.discovery._probe_mutter", lambda: None)
    with pytest.raises(DiscoveryError):
        list_outputs()


def test_list_outputs_prefers_niri(monkeypatch: pytest.MonkeyPatch) -> None:
    niri = _parse_niri_outputs(NIRI_FIXTURE)
    monkeypatch.setattr("openbrightness.due.discovery._probe_niri", lambda: niri)
    monkeypatch.setattr(
        "openbrightness.due.discovery._probe_mutter",
        lambda: pytest.fail("mutter probe should not run"),
    )
    outputs = list_outputs()
    assert outputs[0].connector == "eDP-1"
