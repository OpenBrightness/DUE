"""ControlManager tests (PLAN.md section 11.6) — fake clock/backend, no hardware."""

from __future__ import annotations

import numpy as np

from openbrightness.due.control.base import DisplayControlBackend, WriteLedger
from openbrightness.due.control.manager import ControlManager
from openbrightness.due.models import LuminanceMetrics


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeBackend(DisplayControlBackend):
    def __init__(self, initial: float = 0.9) -> None:
        self.value = initial
        self.writes: list[float] = []

    def get_brightness(self) -> float | None:
        return self.value

    def set_brightness(self, value: float) -> bool:
        self.writes.append(value)
        self.value = value
        return True

    def describe(self) -> str:
        return "fake backlight"


def metrics(
    mean: float, dark: float = 0.0, delta: float | None = 0.0
) -> LuminanceMetrics:
    return LuminanceMetrics(
        mean_luminance=mean,
        median_luminance=mean,
        p10_luminance=0.0,
        p90_luminance=255.0,
        dark_ratio=dark,
        bright_ratio=0.0,
        rms_contrast=10.0,
        temporal_delta=delta,
        histogram=np.zeros(64, dtype=np.float32),
        capture_latency_ms=0.0,
        analysis_latency_ms=0.0,
        width=480,
        height=300,
        timestamp_monotonic_ns=0,
    )


def make_manager(clock: FakeClock, backend: FakeBackend | None = None, **kw: object):
    backend = backend if backend is not None else FakeBackend()
    manager = ControlManager(
        backend,
        connector="eDP-1",
        clock=clock,
        **kw,  # type: ignore[arg-type]
    )
    return manager, backend


def test_disabled_means_zero_writes() -> None:
    clock = FakeClock()
    manager, backend = make_manager(clock)
    for _ in range(50):
        manager.on_metrics(metrics(mean=0.0, dark=1.0))
        clock.advance(10.0)
    manager.wait_idle()
    assert backend.writes == []
    assert manager.ledger.count() == 0
    manager.stop()


def test_enable_captures_baseline_and_dims() -> None:
    clock = FakeClock()
    manager, backend = make_manager(clock)
    manager.enable()
    assert manager.status().baseline == 0.9
    manager.on_metrics(metrics(mean=0.0, dark=1.0))
    manager.wait_idle()
    assert backend.writes, "expected a dimming write"
    assert backend.writes[0] < 0.9
    manager.stop()


def test_deadband_blocks_micro_changes() -> None:
    clock = FakeClock()
    manager, backend = make_manager(clock, deadband=0.05, min_write_interval=0.0)
    manager.enable()
    manager.on_metrics(metrics(mean=0.0, dark=1.0))  # first write
    manager.wait_idle()
    first_writes = len(backend.writes)
    # near-identical content: smoothed target stays inside the deadband
    for _ in range(20):
        manager.on_metrics(metrics(mean=1.0, dark=0.99))
        clock.advance(10.0)
    manager.wait_idle()
    assert len(backend.writes) == first_writes
    manager.stop()


def test_rate_limit_blocks_rapid_writes() -> None:
    clock = FakeClock()
    manager, backend = make_manager(clock, deadband=0.0, min_write_interval=2.0)
    manager.enable()
    for _ in range(10):
        manager.on_metrics(metrics(mean=0.0, dark=1.0))
        clock.advance(0.1)  # faster than the 2 s interval
    manager.wait_idle()
    assert len(backend.writes) <= 1
    # after the interval passes, the next tick may write again
    clock.advance(2.5)
    manager.on_metrics(metrics(mean=0.0, dark=1.0))
    manager.wait_idle()
    assert len(backend.writes) == 2
    manager.stop()


def test_motion_freeze_blocks_writes() -> None:
    clock = FakeClock()
    manager, backend = make_manager(clock, deadband=0.0, min_write_interval=0.0)
    manager.enable()
    manager.on_metrics(metrics(mean=0.0, dark=1.0, delta=0.0))  # seed
    manager.wait_idle()
    writes = len(backend.writes)
    for _ in range(30):
        manager.on_metrics(metrics(mean=255.0, dark=0.0, delta=0.9))  # video
        clock.advance(1.0)
    manager.wait_idle()
    assert len(backend.writes) == writes
    manager.stop()


def test_manual_override_inhibits_and_rebaselines() -> None:
    clock = FakeClock()
    backend = FakeBackend(initial=0.9)
    manager, _ = make_manager(clock, backend=backend, min_write_interval=2.0)
    manager.enable()
    manager.on_metrics(metrics(mean=0.0, dark=1.0))
    manager.wait_idle()
    # simulate the user pressing brightness keys
    backend.value = 0.5
    clock.advance(3.0)  # past the settle window
    manager.on_metrics(metrics(mean=0.0, dark=1.0))
    manager.wait_idle()
    status = manager.status()
    assert status.inhibited_until is not None
    assert status.baseline == 0.5  # user's value adopted
    writes_during_inhibit = len(backend.writes)
    for _ in range(10):
        manager.on_metrics(metrics(mean=0.0, dark=1.0))
        clock.advance(10.0)
    manager.wait_idle()
    assert len(backend.writes) == writes_during_inhibit  # fully inhibited
    manager.stop()


def test_inhibit_expires() -> None:
    clock = FakeClock()
    backend = FakeBackend(initial=0.9)
    manager, _ = make_manager(
        clock, backend=backend, min_write_interval=0.0, inhibit_seconds=300.0
    )
    manager.enable()
    manager.on_metrics(metrics(mean=0.0, dark=1.0))
    manager.wait_idle()
    backend.value = 0.5  # user change
    clock.advance(3.0)
    manager.on_metrics(metrics(mean=0.0, dark=1.0))
    assert manager.status().inhibited_until is not None
    clock.advance(301.0)  # inhibit expired
    manager.on_metrics(metrics(mean=0.0, dark=1.0))
    manager.wait_idle()
    assert manager.status().inhibited_until is None
    assert manager.status().baseline == 0.5
    manager.stop()


def test_disable_restores_baseline() -> None:
    clock = FakeClock()
    manager, backend = make_manager(clock, deadband=0.0, min_write_interval=0.0)
    manager.enable()
    manager.on_metrics(metrics(mean=0.0, dark=1.0))  # dims
    manager.wait_idle()
    assert backend.value < 0.9
    manager.disable()
    manager.wait_idle()
    assert backend.value == 0.9  # restored
    assert manager.status().auto_enabled is False
    manager.stop()


def test_stop_keeps_current_brightness() -> None:
    clock = FakeClock()
    manager, backend = make_manager(clock, deadband=0.0, min_write_interval=0.0)
    manager.enable()
    manager.on_metrics(metrics(mean=0.0, dark=1.0))
    manager.wait_idle()
    dimmed = backend.value
    manager.stop()
    assert backend.value == dimmed  # decision 2: no restore on exit


def test_ledger_counts_writes() -> None:
    clock = FakeClock()
    ledger = WriteLedger()
    backend = FakeBackend()
    manager = ControlManager(
        backend, connector="eDP-1", clock=clock, ledger=ledger,
        deadband=0.0, min_write_interval=0.0,
    )
    manager.enable()
    manager.on_metrics(metrics(mean=0.0, dark=1.0))
    manager.on_metrics(metrics(mean=0.0, dark=1.0))
    manager.wait_idle()
    assert ledger.count("eDP-1") == len(backend.writes) > 0
    assert all(0.0 <= v <= 1.0 for v in ledger.values("eDP-1"))
    manager.stop()


def test_unsupported_backend_never_enables() -> None:
    clock = FakeClock()
    manager = ControlManager(None, connector="HDMI-A-1", clock=clock)
    manager.enable()
    assert manager.status().auto_enabled is False
    assert manager.status().supported is False
    manager.on_metrics(metrics(mean=0.0, dark=1.0))
    manager.wait_idle()
    assert manager.ledger.count() == 0
    manager.stop()
