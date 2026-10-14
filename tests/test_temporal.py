"""Tests for the TemporalTracker (PLAN_V1.md section 4)."""

from __future__ import annotations

import pytest

from openbrightness.due.temporal.tracker import TemporalTracker
from tests.conftest import make_frame, uniform


def test_first_frame_returns_none() -> None:
    tracker = TemporalTracker()
    assert tracker.update(make_frame(uniform(0))) is None


def test_identical_frames_zero_delta() -> None:
    tracker = TemporalTracker()
    tracker.update(make_frame(uniform(100)))
    delta = tracker.update(make_frame(uniform(100)))
    assert delta == pytest.approx(0.0, abs=1e-6)


def test_delta_normalized_to_unit_range() -> None:
    tracker = TemporalTracker()
    tracker.update(make_frame(uniform(0, 16, 16)))
    delta = tracker.update(make_frame(uniform(255, 16, 16)))
    assert delta == pytest.approx(1.0, abs=1e-6)


def test_delta_half_range() -> None:
    tracker = TemporalTracker()
    tracker.update(make_frame(uniform(0, 16, 16)))
    delta = tracker.update(make_frame(uniform(128, 16, 16)))
    assert delta == pytest.approx(128 / 255, abs=1e-3)


def test_resolution_change_rebases_without_delta() -> None:
    tracker = TemporalTracker()
    tracker.update(make_frame(uniform(0, 16, 16)))
    assert tracker.update(make_frame(uniform(255, 32, 32))) is None
    delta = tracker.update(make_frame(uniform(255, 32, 32)))
    assert delta == pytest.approx(0.0, abs=1e-6)


def test_reset_drops_history() -> None:
    tracker = TemporalTracker()
    tracker.update(make_frame(uniform(0, 16, 16)))
    tracker.update(make_frame(uniform(255, 16, 16)))
    assert tracker.delta_max is not None
    tracker.reset()
    assert tracker.delta_mean is None
    assert tracker.delta_min is None
    assert tracker.delta_max is None
    assert tracker.frame_count == 0
    assert tracker.update(make_frame(uniform(0, 16, 16))) is None


def test_history_statistics() -> None:
    tracker = TemporalTracker()
    tracker.update(make_frame(uniform(0, 16, 16)))
    d1 = tracker.update(make_frame(uniform(255, 16, 16)))
    d2 = tracker.update(make_frame(uniform(0, 16, 16)))
    assert d1 is not None and d2 is not None
    assert tracker.delta_mean == pytest.approx((d1 + d2) / 2)
    assert tracker.delta_min == pytest.approx(min(d1, d2))
    assert tracker.delta_max == pytest.approx(max(d1, d2))
    assert tracker.frame_count == 3


def test_subsample_step_validation() -> None:
    with pytest.raises(ValueError, match="step"):
        TemporalTracker(subsample_step=0)


def test_partial_frame_change() -> None:
    tracker = TemporalTracker()
    frame_a = make_frame(uniform(0, 16, 16))
    data_b = uniform(0, 16, 16).copy()
    data_b[:, :8, :] = 255
    frame_b = make_frame(data_b)
    tracker.update(frame_a)
    delta = tracker.update(frame_b)
    assert delta is not None
    assert 0.0 < delta < 1.0
