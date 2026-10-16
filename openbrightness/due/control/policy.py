"""Adaptive brightness policy — pure and deterministic (PLAN.md section 11.4).

Content-adaptive dimming: when the screen is dark, gently dim the backlight
toward a floor (the content is dark anyway — less total light on the eyes);
bright content returns to the user's baseline. Dim-only: the target never
exceeds the baseline the user set.
"""

from __future__ import annotations

from dataclasses import dataclass

from openbrightness.due.models import LuminanceMetrics

# Defaults (PLAN.md 11.4); all overridable via PolicyConfig.
FACTOR_MIN = 0.6
ALPHA = 0.2
MOTION_FREEZE_THRESHOLD = 0.05


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    """Tunable policy constants (config-overridable)."""

    factor_min: float = FACTOR_MIN
    alpha: float = ALPHA
    motion_freeze_threshold: float = MOTION_FREEZE_THRESHOLD

    def __post_init__(self) -> None:
        if not 0.0 < self.factor_min <= 1.0:
            raise ValueError(f"factor_min must be in (0, 1], got {self.factor_min}")
        if not 0.0 < self.alpha <= 1.0:
            raise ValueError(f"alpha must be in (0, 1], got {self.alpha}")
        if self.motion_freeze_threshold < 0.0:
            raise ValueError("motion_freeze_threshold must be >= 0")


class AdaptiveBrightnessPolicy:
    """Maps LuminanceMetrics to a smoothed dim-only brightness target.

    Pure state machine: no I/O, no clock — deterministic under test.
    State is the EMA of the raw target; ``reset()`` clears it (e.g. on
    toggle-off or baseline change).
    """

    def __init__(self, config: PolicyConfig | None = None) -> None:
        self._config = config or PolicyConfig()
        self._ema: float | None = None

    @property
    def factor_min(self) -> float:
        return self._config.factor_min

    def reset(self) -> None:
        self._ema = None

    def _raw_target(self, metrics: LuminanceMetrics, baseline: float) -> float:
        """Content 'need for light' S ∈ [0, 1] → factor ∈ [factor_min, 1]."""
        mean_norm = max(0.0, min(1.0, metrics.mean_luminance / 255.0))
        dark = max(0.0, min(1.0, metrics.dark_ratio))
        s = 0.6 * mean_norm + 0.4 * (1.0 - dark)
        factor = self._config.factor_min + (1.0 - self._config.factor_min) * s
        return baseline * factor

    def update(self, metrics: LuminanceMetrics, baseline: float) -> float | None:
        """Feed one metric sample; return the smoothed target or ``None``.

        ``None`` means hold: motion freeze (video playback) or first call
        after ``reset()`` still returns a target — the first sample seeds the
        EMA directly. Freeze holds state and returns ``None``.
        """
        if not 0.0 <= baseline <= 1.0:
            raise ValueError(f"baseline must be in [0, 1], got {baseline}")

        delta = metrics.temporal_delta
        if (
            delta is not None
            and delta > self._config.motion_freeze_threshold
            and self._ema is not None
        ):
            return None  # motion freeze: hold, no policy update

        raw = self._raw_target(metrics, baseline)
        raw = min(raw, baseline)  # dim-only invariant
        if self._ema is None:
            self._ema = raw
        else:
            a = self._config.alpha
            self._ema = a * raw + (1.0 - a) * self._ema
        return min(self._ema, baseline)
