"""CI-safe performance smoke test (PLAN.md M7).

Uses small frame counts and generous CI thresholds; the strict hardware
targets are validated by `python -m openbrightness.due.benchmark` on the
target machine (PLAN.md section 9).
"""

from __future__ import annotations

from openbrightness.due.analysis.luminance import LuminanceAnalyzer, frame_luma
from openbrightness.due.benchmark import _synthetic_frame, run_benchmark


def test_benchmark_smoke_runs_and_reports() -> None:
    results = run_benchmark(frames=25, width=640, height=480)
    assert results["frames"] == 25
    for key in ("extract_mean_ms", "analysis_mean_ms", "total_mean_ms", "rss_growth_kb"):
        assert results[key] >= 0.0


def test_analysis_latency_ci_bound() -> None:
    frame = _synthetic_frame(640, 480, 0)
    analyzer = LuminanceAnalyzer()
    y, _w, _h = frame_luma(frame)
    analyzer.analyze(frame, luma=y)  # warm-up
    import time

    t0 = time.perf_counter_ns()
    for i in range(20):
        frame = _synthetic_frame(640, 480, i)
        y, _w, _h = frame_luma(frame)
        analyzer.analyze(frame, luma=y)
    mean_ms = (time.perf_counter_ns() - t0) / 1e6 / 20
    assert mean_ms < 20.0, f"analysis mean {mean_ms:.1f} ms exceeds CI bound"


def test_shared_luma_matches_recomputed() -> None:
    frame = _synthetic_frame(320, 240, 7)
    analyzer = LuminanceAnalyzer()
    direct = analyzer.analyze(frame)
    y, w, h = frame_luma(frame)
    shared = analyzer.analyze(frame, luma=y)
    assert (shared.width, shared.height) == (w, h) == (direct.width, direct.height)
    assert shared.mean_luminance == direct.mean_luminance
    assert shared.p10_luminance == direct.p10_luminance
    assert shared.p90_luminance == direct.p90_luminance
    assert shared.median_luminance == direct.median_luminance
    assert shared.rms_contrast == direct.rms_contrast
    assert shared.dark_ratio == direct.dark_ratio
    assert shared.bright_ratio == direct.bright_ratio
