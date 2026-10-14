"""Shared synthetic-frame fixtures for the DUE test suite."""

from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray

from openbrightness.due.models import DisplayFrame


def make_frame(rgb: NDArray[np.uint8], pts_ns: int | None = None) -> DisplayFrame:
    h, w = rgb.shape[:2]
    return DisplayFrame(
        data=np.ascontiguousarray(rgb),
        width=w,
        height=h,
        pts_ns=pts_ns,
        captured_monotonic_ns=0,
    )


def uniform(value: int, h: int = 120, w: int = 160) -> NDArray[np.uint8]:
    return np.full((h, w, 3), value, dtype=np.uint8)


def gray_ramp(h: int = 100, w: int = 256) -> NDArray[np.uint8]:
    row = np.linspace(0, 255, w, dtype=np.uint8)
    plane = np.tile(row, (h, 1))
    return np.stack([plane, plane, plane], axis=-1)


def checkerboard(value_a: int = 0, value_b: int = 255, n: int = 8, cell: int = 16) -> NDArray[np.uint8]:
    ys, xs = np.mgrid[0 : n * cell, 0 : n * cell]
    mask = ((ys // cell) + (xs // cell)) % 2 == 0
    out = np.where(mask[..., None], value_a, value_b).astype(np.uint8)
    return np.ascontiguousarray(np.repeat(out, 3, axis=-1))


@pytest.fixture
def black_frame() -> DisplayFrame:
    return make_frame(uniform(0))


@pytest.fixture
def white_frame() -> DisplayFrame:
    return make_frame(uniform(255))


@pytest.fixture
def mid_gray_frame() -> DisplayFrame:
    return make_frame(uniform(128))


@pytest.fixture
def gradient_frame() -> DisplayFrame:
    return make_frame(gray_ramp())


@pytest.fixture
def checker_frame() -> DisplayFrame:
    return make_frame(checkerboard())
