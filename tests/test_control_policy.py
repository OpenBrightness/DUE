"""Policy engine tests (PLAN.md section 11.4) — pure, no hardware."""

from __future__ import annotations

import numpy as np
import pytest

from openbrightness.due.control.policy import AdaptiveBrightnessPolicy, PolicyConfig
from openbrightness.due.models import LuminanceMetrics


def metrics(
    mean: float, dark: float = 0.0, delta: float | None = 0.0, bright: float = 0.0
) -> LuminanceMetrics:
    return LuminanceMetrics(
        mean_luminance=mean,
        median_luminance=mean,
        p10_luminance=mean * 0.5,
        p90_luminance=min(mean * 1.5, 255.0),
        dark_ratio=dark,
        bright_ratio=bright,
        rms_contrast=10.0,
        temporal_delta=delta,
        histogram=np.zeros(64, dtype=np.float32),
        capture_latency_ms=0.0,
        analysis_latency_ms=0.0,
        width=480,
        height=300,
        timestamp_monotonic_ns=0,
    )


def test_bright_content_returns_to_baseline() -> None:
    policy = AdaptiveBrightnessPolicy()
    # mean 255, no dark pixels → S = 1 → factor = 1 → target = baseline
    target = policy.update(metrics(mean=255.0, dark=0.0), baseline=0.9)
    assert target == pytest.approx(0.9)


def test_dark_content_dims_below_baseline() -> None:
    policy = AdaptiveBrightnessPolicy()
    target = policy.update(metrics(mean=10.0, dark=0.95), baseline=0.9)
    assert target is not None
    assert target < 0.9  # dim-only: below baseline
    assert target >= 0.6 * 0.9  # never below factor_min·baseline


def test_dim_only_invariant_always_holds() -> None:
    policy = AdaptiveBrightnessPolicy()
    rng = np.random.default_rng(42)
    for _ in range(500):
        mean = float(rng.uniform(0, 255))
        dark = float(rng.uniform(0, 1))
        baseline = float(rng.uniform(0.1, 1.0))
        target = policy.update(metrics(mean=mean, dark=dark), baseline=baseline)
        assert target is not None
        assert target <= baseline + 1e-9


def test_factor_clamp_bounds() -> None:
    config = PolicyConfig(factor_min=0.75)
    policy = AdaptiveBrightnessPolicy(config)
    # darkest possible input → factor floor
    target = policy.update(metrics(mean=0.0, dark=1.0), baseline=1.0)
    assert target == pytest.approx(0.75)
    # brightest possible input → factor 1
    policy.reset()
    target = policy.update(metrics(mean=255.0, dark=0.0), baseline=1.0)
    assert target == pytest.approx(1.0)


def test_ema_smoothing_converges() -> None:
    policy = AdaptiveBrightnessPolicy(PolicyConfig(alpha=0.2, factor_min=0.6))
    first = policy.update(metrics(mean=0.0, dark=1.0), baseline=1.0)
    assert first == pytest.approx(0.6)  # seeds directly
    # sustained bright input → EMA climbs toward 1.0 but not instantly
    second = policy.update(metrics(mean=255.0, dark=0.0), baseline=1.0)
    assert second is not None
    assert 0.6 < second < 1.0
    for _ in range(50):
        policy.update(metrics(mean=255.0, dark=0.0), baseline=1.0)
    final = policy.update(metrics(mean=255.0, dark=0.0), baseline=1.0)
    assert final == pytest.approx(1.0, abs=1e-4)


def test_motion_freeze_holds_state() -> None:
    policy = AdaptiveBrightnessPolicy(PolicyConfig(motion_freeze_threshold=0.05))
    policy.update(metrics(mean=0.0, dark=1.0, delta=0.0), baseline=1.0)
    # video motion → freeze: no update, no target
    assert policy.update(metrics(mean=255.0, dark=0.0, delta=0.9), baseline=1.0) is None
    # freeze does not corrupt state: resume with calm input continues
    resumed = policy.update(metrics(mean=255.0, dark=0.0, delta=0.0), baseline=1.0)
    assert resumed is not None
    assert resumed < 1.0  # still smoothing toward the new input


def test_first_sample_not_frozen_even_with_motion() -> None:
    policy = AdaptiveBrightnessPolicy()
    # after reset there is no state to protect: a target is still produced
    target = policy.update(metrics(mean=128.0, dark=0.5, delta=0.9), baseline=1.0)
    assert target is not None


def test_reset_clears_state() -> None:
    policy = AdaptiveBrightnessPolicy()
    policy.update(metrics(mean=0.0, dark=1.0), baseline=1.0)
    policy.reset()
    target = policy.update(metrics(mean=255.0, dark=0.0), baseline=1.0)
    assert target == pytest.approx(1.0)  # seeded fresh, no smoothing lag


def test_invalid_baseline_rejected() -> None:
    policy = AdaptiveBrightnessPolicy()
    with pytest.raises(ValueError, match="baseline"):
        policy.update(metrics(mean=128.0), baseline=1.5)


def test_invalid_config_rejected() -> None:
    with pytest.raises(ValueError, match="factor_min"):
        PolicyConfig(factor_min=0.0)
    with pytest.raises(ValueError, match="alpha"):
        PolicyConfig(alpha=0.0)
