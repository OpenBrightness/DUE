"""Tests for the CLI entry point and backend selection (M5)."""

from __future__ import annotations

import pytest

from openbrightness.due.__main__ import build_backend_factory, parse_args
from openbrightness.due.capture.mock import MockCaptureBackend
from openbrightness.due.capture.wlr import WlrScreencopyBackend
from openbrightness.due.models import OutputInfo

OUTPUT = OutputInfo("eDP-1", "BOE", "X", 1920, 1200, 60.0)


def test_parse_args_defaults() -> None:
    args = parse_args([])
    assert args.display is None
    assert args.backend == "auto"
    assert args.list_outputs is False
    assert args.verbose is False


def test_parse_args_full() -> None:
    args = parse_args(["--display", "eDP-1", "--backend", "mock", "-v"])
    assert args.display == "eDP-1"
    assert args.backend == "mock"
    assert args.verbose is True


def test_parse_args_rejects_unknown_backend() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--backend", "portal"])


def test_backend_factory_mock() -> None:
    backend = build_backend_factory("mock")(OUTPUT)
    assert isinstance(backend, MockCaptureBackend)
    backend.stop()


def test_backend_factory_auto_is_wlr() -> None:
    backend = build_backend_factory("auto")(OUTPUT)
    assert isinstance(backend, WlrScreencopyBackend)
    backend.stop()


def test_backend_factory_wlr() -> None:
    backend = build_backend_factory("wlr")(OUTPUT)
    assert isinstance(backend, WlrScreencopyBackend)
    backend.stop()


def test_list_outputs_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    from openbrightness.due import __main__ as main_mod

    outputs = [
        OutputInfo("eDP-1", "BOE", "X", 1920, 1200, 60.0, is_primary=True),
        OutputInfo("HDMI-A-1", "LG", "Y", 2560, 1440, 144.0),
    ]
    monkeypatch.setattr(main_mod, "list_outputs", lambda: outputs)
    assert main_mod.main(["--list-outputs"]) == 0


def test_display_not_found_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    from openbrightness.due import __main__ as main_mod

    outputs = [OutputInfo("eDP-1", "BOE", "X", 1920, 1200, 60.0)]
    monkeypatch.setattr(main_mod, "list_outputs", lambda: outputs)
    assert main_mod.main(["--display", "DP-9"]) == 1
