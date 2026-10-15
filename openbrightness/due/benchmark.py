"""1,000-frame pipeline benchmark (PLAN.md sections 8-9).

Measures the two pipeline stages on target-panel geometry synthetic frames:
- extract: capture-side BGRx→RGB copy + subsample gather (as in capture/wlr.py)
- analysis: coordinator worker path (shared luma + temporal + metrics)

Run: python -m openbrightness.due.benchmark [--frames 1000] [--width 1920] [--height 1200]
"""

from __future__ import annotations

import argparse
import gc
import resource
import statistics
import time
from typing import Any

import numpy as np
from numpy.typing import NDArray

from openbrightness.due.analysis.luminance import LuminanceAnalyzer, frame_luma
from openbrightness.due.capture.wlr import bgrx_to_rgb
from openbrightness.due.models import DisplayFrame
from openbrightness.due.temporal.tracker import TemporalTracker

_TARGET_EXTRACT_MS = 5.0  # full-frame BGRx→RGB owned copy (PLAN.md §9)
_TARGET_ANALYSIS_MS = 2.0
_TARGET_TOTAL_MS = 25.0


def _current_rss_kb() -> float:
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1])
    except OSError:
        pass
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


_buffer_cache: dict[tuple[int, int], NDArray[np.uint8]] = {}
_grid_cache: dict[tuple[int, int], Any] = {}


def _synthetic_frame(width: int, height: int, index: int) -> DisplayFrame:
    key = (width, height)
    data = _buffer_cache.get(key)
    if data is None:
        data = np.empty((height, width, 3), dtype=np.uint8)
        _buffer_cache[key] = data
        _grid_cache[key] = np.mgrid[0:height, 0:width]
    ys, xs = _grid_cache[key]
    data[..., 0] = ((xs + index * 3) % 256).astype(np.uint8)
    data[..., 1] = ((ys + index * 5) % 256).astype(np.uint8)
    data[..., 2] = (((xs // 4) + (ys // 4) + index) % 256).astype(np.uint8)
    return DisplayFrame(
        data=data,
        width=width,
        height=height,
        pts_ns=None,
        captured_monotonic_ns=time.monotonic_ns(),
    )


def run_benchmark(
    frames: int = 1000, width: int = 1920, height: int = 1200
) -> dict[str, float]:
    analyzer = LuminanceAnalyzer()
    tracker = TemporalTracker()

    extract_ms: list[float] = []
    analysis_ms: list[float] = []
    total_ms: list[float] = []

    # simulate the capture-side BGRx shm buffer the wlr backend delivers
    bgrx = np.empty((height, width, 4), dtype=np.uint8)
    bgrx[..., 3] = 0

    rss_before = _current_rss_kb()

    for i in range(frames):
        frame = _synthetic_frame(width, height, i)
        np.copyto(bgrx[..., :3], frame.data[:, :, ::-1])

        t0 = time.perf_counter_ns()
        rgb = bgrx_to_rgb(bgrx, width, height, width * 4, y_invert=False)
        owned = DisplayFrame(
            data=rgb, width=width, height=height,
            pts_ns=None, captured_monotonic_ns=time.monotonic_ns(),
        )
        y, _sub_w, _sub_h = frame_luma(owned)
        t1 = time.perf_counter_ns()

        delta = tracker.update(owned, luma=y)
        analyzer.analyze(owned, temporal_delta=delta, luma=y)
        t2 = time.perf_counter_ns()

        extract_ms.append((t1 - t0) / 1e6)
        analysis_ms.append((t2 - t1) / 1e6)
        total_ms.append((t2 - t0) / 1e6)

        if i % 100 == 0:
            gc.collect()

    rss_after = _current_rss_kb()

    def pct(values: list[float], p: float) -> float:
        return float(np.percentile(np.array(values), p))

    return {
        "frames": frames,
        "extract_mean_ms": statistics.fmean(extract_ms),
        "extract_p95_ms": pct(extract_ms, 95),
        "analysis_mean_ms": statistics.fmean(analysis_ms),
        "analysis_p95_ms": pct(analysis_ms, 95),
        "total_mean_ms": statistics.fmean(total_ms),
        "total_p95_ms": pct(total_ms, 95),
        "total_max_ms": max(total_ms),
        "rss_growth_kb": float(rss_after - rss_before),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DUE pipeline benchmark")
    parser.add_argument("--frames", type=int, default=1000)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1200)
    args = parser.parse_args(argv)

    results = run_benchmark(args.frames, args.width, args.height)

    print(f"benchmark: {results['frames']} frames @ {args.width}x{args.height}")
    print(f"  extract : mean {results['extract_mean_ms']:6.2f} ms  p95 {results['extract_p95_ms']:6.2f} ms"
          f"   (target < {_TARGET_EXTRACT_MS} ms)")
    print(f"  analysis: mean {results['analysis_mean_ms']:6.2f} ms  p95 {results['analysis_p95_ms']:6.2f} ms"
          f"   (target < {_TARGET_ANALYSIS_MS} ms)")
    print(f"  total   : mean {results['total_mean_ms']:6.2f} ms  p95 {results['total_p95_ms']:6.2f} ms"
          f"  max {results['total_max_ms']:6.2f} ms   (target < {_TARGET_TOTAL_MS} ms)")
    print(f"  RSS growth: {results['rss_growth_kb'] / 1024:.1f} MB")

    ok = (
        results["analysis_mean_ms"] < _TARGET_ANALYSIS_MS
        and results["total_mean_ms"] < _TARGET_TOTAL_MS
    )
    print("PASS" if ok else "FAIL (analysis mean <2 ms and total mean <25 ms required)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
