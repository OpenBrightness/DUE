"""Executable safety invariants (PLAN.md section 11.6 + V2-M5 soak)."""

from __future__ import annotations

import numpy as np

from openbrightness.due.control.base import WriteLedger
from openbrightness.due.control.manager import ABS_FLOOR, ControlManager
from openbrightness.due.models import OutputInfo
from tests.test_control_manager import FakeBackend, FakeClock, metrics


def test_soak_10k_frames_internal_only_writes() -> None:
    """V2-M5 soak (deterministic): 10k synthetic metric frames through
    policy+manager → writes only ever target the internal connector and no
    write falls outside [floor, baseline]."""
    clock = FakeClock()
    ledger = WriteLedger()
    backend = FakeBackend(initial=0.95)
    manager = ControlManager(
        backend,
        connector="eDP-1",
        clock=clock,
        ledger=ledger,
        deadband=0.0,
        min_write_interval=0.0,
    )
    manager.enable()
    rng = np.random.default_rng(7)
    for i in range(10_000):
        mean = float(rng.uniform(0, 255))
        dark = float(rng.uniform(0, 1))
        delta = 0.9 if i % 50 == 0 else 0.0  # periodic video-like motion
        manager.on_metrics(metrics(mean=mean, dark=dark, delta=delta))
        clock.advance(1.0)
    manager.wait_idle()
    manager.stop()

    assert ledger.count() > 0
    assert ledger.count("HDMI-A-1") == 0  # external: zero auto writes
    for value in ledger.values("eDP-1"):
        assert ABS_FLOOR - 1e-9 <= value <= 0.95 + 1e-9


def test_toggle_off_is_zero_write_guarantee() -> None:
    clock = FakeClock()
    backend = FakeBackend(initial=0.9)
    manager = ControlManager(backend, connector="eDP-1", clock=clock)
    manager.disable()
    for _ in range(100):
        manager.on_metrics(metrics(mean=0.0, dark=1.0))
        clock.advance(10.0)
    manager.wait_idle()
    assert backend.writes == []
    manager.stop()


def test_target_never_exceeds_baseline() -> None:
    clock = FakeClock()
    backend = FakeBackend(initial=0.5)
    manager = ControlManager(
        backend, connector="eDP-1", clock=clock,
        deadband=0.0, min_write_interval=0.0,
    )
    manager.enable()
    for mean in (0.0, 64.0, 128.0, 200.0, 255.0):
        manager.on_metrics(metrics(mean=mean, dark=0.2))
        clock.advance(10.0)
    manager.wait_idle()
    assert all(v <= 0.5 + 1e-9 for v in backend.writes)
    manager.stop()


def test_floor_never_blacks_out_panel() -> None:
    clock = FakeClock()
    backend = FakeBackend(initial=0.1)  # very low user baseline
    manager = ControlManager(
        backend, connector="eDP-1", clock=clock,
        deadband=0.0, min_write_interval=0.0,
    )
    manager.enable()
    manager.on_metrics(metrics(mean=0.0, dark=1.0))
    manager.wait_idle()
    assert backend.writes
    assert all(v >= ABS_FLOOR - 1e-9 for v in backend.writes)
    manager.stop()


def test_external_output_gets_no_control_manager() -> None:
    """11.6 invariant 5: routing by OutputInfo.is_internal."""
    external = OutputInfo("HDMI-A-1", "BenQ", "GW2490", 1920, 1080, 60.0)
    assert external.is_internal is False
    internal = OutputInfo("eDP-1", "LG", "X", 1920, 1200, 60.0)
    assert internal.is_internal is True


def test_enable_records_baseline_not_writes() -> None:
    clock = FakeClock()
    backend = FakeBackend(initial=0.8)
    ledger = WriteLedger()
    manager = ControlManager(backend, connector="eDP-1", clock=clock, ledger=ledger)
    manager.enable()
    manager.wait_idle()
    assert ledger.count() == 0  # capturing a baseline is not a write
    manager.stop()
