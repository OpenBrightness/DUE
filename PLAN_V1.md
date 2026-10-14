# OpenBrightness DUE V1 — Reconciled Implementation Plan (`PLAN_V1.md`)

**Project:** OpenBrightness — Display Understanding Engine (DUE)
**Document Type:** Authoritative V1 Implementation Plan (supersedes `PLAN.md` where they differ)
**Target Platform:** Fedora Linux 44 (x86_64), Niri Wayland Compositor (26.04), Linux Kernel 7.1.x
**Status:** Approved for implementation — 2026-10-14

---

## 0. What Changed from `PLAN.md` (Reconciliation Summary)

This plan resolves the defects found during review of `PLAN.md` V1:

| # | Defect in `PLAN.md` | Resolution in `PLAN_V1.md` |
|---|---|---|
| 1 | Monitor selection (`--display`, TUI picker) unsatisfiable on `PortalGstBackend` — the portal shows its own picker dialog and accepts no connector argument | **Capture pivoted to `WlrScreencopyBackend` (zwlr_screencopy_manager_v1 + wl_shm)** — honors connector selection natively, no dialog (see §0.A for why GStreamer was dropped) |
| 2 | Latency contradiction: M7 "<5 ms total" vs §8.2/AC9 "<25 ms" | Single target everywhere: **total pipeline < 25 ms** end-to-end at 1 FPS. The "<5 ms" figure is retired |
| 3 | `discovery` module mandated (§1.1) but missing from file tree and milestones | Added `openbrightness/due/discovery.py` (M2) with a defined enumeration mechanism |
| 4 | "Zero-copy" `get_subsampled()` view is unsafe after `Gst.Buffer.unmap()`; ndarray construction ignores rowstride | Moot for the wl_shm path (frames are copied into owned arrays by design) — `get_subsampled()` returns a **contiguous copy** (deliberate, documented) |
| 5 | `median_luminance` and `p50_luminance` duplicated in `LuminanceMetrics` | Single `median_luminance` (= P50); percentiles are P10/P50/P90 |
| 6 | IDEA.md schedules rate-limited DDC/CI for V3; `PLAN.md` declares "permanent exclusion" and misattributes the veto to the research report | **DDC/CI is deferred to V3 per IDEA.md.** V1 is strictly read-only. `PLAN.md`'s "permanent exclusion" language is retired; the EEPROM hazard is documented as a design constraint on any future control path (deadband ≥ 5%, ≤ 1 write / 10–15 s, smoothing) |
| 7 | GLib main-loop ownership undefined | Moot for the wl_shm path: the capture backend owns one Wayland dispatch thread (see §5) |
| 8 | Error banner promised (M6) but no widget exists | `widgets/status_bar.py` extended to `StatusBanner` (metrics footer + error/notice surface), delivered in M3 |
| 9 | No `tests/` layout despite 6 named test files | File tree includes `tests/`; added `test_coordinator.py`, `test_discovery.py`, `test_wlr_backend.py` |
| 10 | mypy pin drift (`>=1.10.0` vs `>=0.9.0`) | `mypy>=1.10.0` everywhere |
| 11 | "Zero disk I/O guarantee" contradicted by `restore_token` persistence | Restated precisely: **zero image/framebuffer I/O** (no token file needed on the wl_shm path) |
| 12 | M6 promised SIGTERM handling but no module owns signals | `__main__.py` owns SIGINT/SIGTERM handlers and teardown |
| 13 | "Reset history" (`R`) implies undefined history state | `TemporalTracker.reset()` semantics defined in §4.3 |
| 14 | `cursor_mode=1` (hidden cursor) missing from PLAN | wl_shm path: `capture_output(overlay_cursor=0)` — cursor excluded from frames |
| 15 | RMS contrast units drift (IDEA 0–1 vs PLAN 0–127.5) | Canonical: **0–127.5 (σ of Y on 0–255)**; TUI displays the normalized 0–1 value for readability |
| 16 | Benchmark was 1080p but target panel is 1920×1200 | Benchmark and accuracy claims reference the target panel geometry (subsample 480×300) |

### 0.A M4 Capture Pivot (Empirical Finding, 2026-10-14)

The plan originally specified GStreamer (`MutterGstBackend` primary, `PortalGstBackend` fallback).
Live verification on the target machine (Fedora 44 / Niri 26.04 / GStreamer 1.28.6 / pipewire-gstreamer
1.6.8) proved the GStreamer path **unusable for CPU frame analysis**:

- niri's `org.gnome.Mutter.ScreenCast` D-Bus flow works (session → `RecordMonitor` →
  `PipeWireStreamAdded(node_id)` verified live), but the PipeWire node it creates
  (`niri-screen-cast-src`) exposes **only `BGRx` with a DRM modifier list**.
- `pipewiresrc` fails to fixate caps against that modifier list
  (`handle_format_change: assertion 'gst_caps_is_fixed' failed`), and every buffer it
  delivers is a **1-byte placeholder** (`GstMemory size=1`) — verified across
  caps-filter combinations (fixed modifiers, DMA_DRM format, `always-copy`,
  `use-bufferpool=false`, `glupload`/`gldownload`). No DMA-BUF importer elements exist
  in the stock plugin set either. This matches the research report's §4.3 warning
  ("DMA-BUF is a trap for CPU analysis") in its most severe form.
- **`zwlr_screencopy_manager_v1` (v3, verified in the research report §3.5) works
  perfectly**: the compositor copies frames into client-provided `wl_shm` memory —
  plain CPU-readable RAM, exactly what the research recommends ("Prefer linear
  SHM… CPU read of linear RAM is <0.8 ms"). Live-verified: 1920×1200 frames arrive
  with correct stride handling and pixel values.

Consequently: **`WlrScreencopyBackend` (capture/wlr.py) is the primary and only live
backend in V1**, generated protocol bindings are vendored under
`openbrightness/due/_proto/` (source XML in `protocols/`), and the GStreamer backends
are dropped from V1 scope. The portability cost is real: zwlr_screencopy is supported
by niri, sway, and other wlroots-family compositors but **not** GNOME/KDE — portability
via `org.freedesktop.portal.ScreenCast` is deferred until the pipewiresrc DMA-BUF bug
is fixed upstream (track pipewire-gstreamer / GStreamer issues around
`gst_caps_is_fixed` in `handle_format_change`).

---

## 1. Product Definition

DUE is a **local, terminal-based, strictly read-only display perception engine**. It captures ~1 frame/second from a selected monitor, computes luminance/contrast/temporal statistics with vectorized NumPy, and renders a live in-place Textual dashboard. No image is ever written to disk; no display hardware is ever controlled.

### 1.1 V1 Requirements (Mandatory)

| # | Requirement | Owner |
|---|---|---|
| R1 | Python 3.12+, strict typing (`mypy --strict`-clean for `openbrightness/`) | all |
| R2 | Linux / Wayland (Fedora + Niri reference target) | — |
| R3 | Monitor selection via **interactive TUI picker + `--display <connector>` CLI flag** | `discovery` |
| R4 | Modular capture behind a `DisplayCaptureBackend` ABC | `capture` |
| R5 | Fixed ~1 FPS sampling | `capture` |
| R6 | Deterministic vectorized BT.709 statistics | `analysis` |
| R7 | Temporal delta tracking with reset | `temporal` |
| R8 | In-place Textual TUI (no terminal scrollback pollution) | `tui` |
| R9 | **Zero image/framebuffer disk I/O** | all |
| R10 | Zero log spam (quiet by default, `-v` for debug) | all |
| R11 | Strictly read-only: no DDC/CI writes, no `/sys/class/backlight` writes | all |
| R12 | Decoupled pipeline (capture ↛ analysis ↛ UI) | `coordinator` |
| R13 | pytest suite with synthetic-frame fixtures | `tests` |

### 1.2 Non-Goals (V1)

- Any display/brightness control (V2: eDP backlight via logind `SetBrightness`; V3: rate-limited DDC/CI for external monitors per IDEA.md §7).
- ML/OCR content classification, ambient light, GUI, daemon/REST API.
- Sandboxed (Flatpak) distribution — portal code assumes a normal desktop session.

---

## 2. Architecture

### 2.1 Capture Backend Selection (revised — see §0.A)

```
                    ┌──────────────────────────────┐
   --display / TUI ─►      Backend selector        │
                    └──────────────┬───────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │ WlrScreencopyBackend         │  PRIMARY (V1 only live backend)
                    │ zwlr_screencopy_manager_v1   │
                    │ capture_output(cursor=0)     │
                    │ per-output selection native  │
                    └──────────────┬───────────────┘
                                   │ compositor copies into wl_shm (CPU memory)
                                   ▼
                    bgrx_to_rgb(): stride-aware copy → owned RGB ndarray
                                   │
                                   ▼
                    coordinator.Queue(maxsize=1)  (drop-oldest)
                                   │
                                   ▼
                    worker thread: analysis + temporal
                                   │
                                   ▼
                    Textual UI (post_message)
```

- **wlr path (primary and only live backend in V1):** `zwlr_screencopy_manager_v1` v3.
  `capture_output(0, wl_output)` per frame → compositor writes pixels into our
  `wl_shm` pool → we copy to an owned RGB array and recycle the pool. Connector
  selection is native (the `wl_output` is chosen by name), no permission dialog,
  cursor excluded (`overlay_cursor=0`). Verified live on Niri 26.04. Compositor
  support: niri, sway, other wlroots-family — **not** GNOME/KDE (see §0.A).
- **Mock path:** `MockCaptureBackend` generates deterministic synthetic content
  (gradient, checkerboard, luminance sweep) for TUI development, CI, and
  `--backend mock`.
- **GStreamer paths (Mutter/Portal):** dropped from V1 after live verification
  proved `pipewiresrc` DMA-BUF delivery broken on the target stack (§0.A).

### 2.2 File Layout

```
openbrightness/due/
├── __init__.py
├── __main__.py             # CLI entry (`due`): argparse, signals, teardown
├── models.py               # Frozen dataclasses (OutputInfo, DisplayFrame, LuminanceMetrics)
├── discovery.py            # Output enumeration → list[OutputInfo]
├── coordinator.py          # Thread-safe pipeline orchestrator (1-slot queue, worker)
├── _proto/                 # Vendored pywayland bindings (generated, do not edit)
│   ├── wayland.py
│   └── wlr_screencopy_unstable_v1.py
├── capture/
│   ├── __init__.py
│   ├── base.py             # DisplayCaptureBackend ABC + CaptureError hierarchy
│   ├── wlr.py              # PRIMARY: zwlr_screencopy + wl_shm (M4)
│   └── mock.py             # Synthetic frames (M2)
├── analysis/
│   ├── __init__.py
│   └── luminance.py        # LuminanceAnalyzer (M1)
├── temporal/
│   ├── __init__.py
│   └── tracker.py          # TemporalTracker (M1)
├── benchmark.py            # 1,000-frame harness (M7)
└── tui/
    ├── __init__.py
    ├── app.py              # DueApp (M3)
    ├── screens/
    │   ├── __init__.py
    │   ├── select.py       # DisplaySelectScreen (M5)
    │   └── dashboard.py    # DashboardScreen (M3)
    └── widgets/
        ├── __init__.py
        ├── metric_card.py      # LuminanceCard, DistributionCard (M3)
        ├── histogram.py        # 64-bin Unicode bar histogram (M3)
        └── status_bar.py       # TelemetryFooter + StatusBanner (M3/M6)

protocols/
└── wlr-screencopy-unstable-v1.xml   # source XML for the vendored bindings

tests/
├── conftest.py             # synthetic-frame fixtures
├── test_models.py
├── test_analysis.py
├── test_temporal.py
├── test_discovery.py
├── test_mock_backend.py
├── test_wlr_backend.py     # stride/copy logic + backend contract
├── test_coordinator.py
├── test_tui.py
├── test_perf.py            # benchmark smoke (CI-safe thresholds)
└── test_live_capture.py    # manual/integration; auto-skips without a session
```

### 2.3 Data Contracts

All dataclasses are `frozen=True, slots=True`.

**`OutputInfo`** — `connector: str`, `make: str`, `model: str`, `width: int`, `height: int`, `refresh_rate: float`, `is_primary: bool`.

**`DisplayFrame`** — `data: NDArray[np.uint8]` shape `(H, W, 3)`, RGB, **C-contiguous and owned by the frame** (copied out of the capture buffer — §4.2), `width`, `height`, `pts_ns: int | None`, `captured_monotonic_ns: int`.
- `get_subsampled(step: int = 4) -> NDArray[np.uint8]` returns `np.ascontiguousarray(self.data[::step, ::step, :])` — **a copy, deliberately**. Strided views into unmapped DMA/SHM memory are the correctness bug this replaces.

**`LuminanceMetrics`** — `mean_luminance: float`, `median_luminance: float` (= P50), `p10_luminance: float`, `p90_luminance: float`, `dark_ratio: float` (Y < 51), `bright_ratio: float` (Y > 204), `rms_contrast: float` (σ_Y, 0–127.5 canonical; TUI shows /127.5), `temporal_delta: float | None` (0–1.0), `histogram: NDArray[np.float32]` (64 bins, normalized), `capture_latency_ms: float`, `analysis_latency_ms: float`, `width: int`, `height: int`, `timestamp_monotonic_ns: int`.

---

## 3. Analysis Specification

- **Subsampling:** 4× strided subsample with mandatory copy: `ascontiguousarray(Y_full[::4, ::4])`. Measured 22.2× speedup vs full-res (0.94 ms vs 20.78 ms class hardware), < 0.08% mean-luminance error. For 1920×1200 the subsample is 480×300.
- **Luma:** `Y = 0.2126·R + 0.7152·G + 0.0722·B` on the subsample (`float32` promotion; verified against the integer approximation `(54R + 183G + 19B) >> 8`, max error < 0.4/255). Percentiles via `np.percentile(Y, [10, 50, 90])`.
- **Thresholds:** dark ratio at Y < 51 (20%), bright ratio at Y > 204 (80%).
- **Histogram:** 64 bins over 0–255, normalized by pixel count to sum 1.
- **Latency:** `T_capture` = PTS→callback dequeued (monotonic fallback when PTS is absent), `T_analysis` = `perf_counter_ns()` around the analyzer call.

## 4. Temporal Specification

- **Delta:** `temporal_delta = mean(|Y_t − Y_{t−1}|) / 255` on subsampled luma; `None` for the first frame after start/reset/resolution change.
- **Shape change:** if the incoming frame's subsampled shape differs from the stored previous, the tracker silently resets (keeps current as previous) — resolution/scale changes must not crash or produce garbage deltas.
- **`reset()`** (`R` key / reconnect): drops stored previous frame and any accumulated history (min/max/mean of `temporal_delta`, frame count). Next frame reports `temporal_delta=None`.

## 5. Threading & Concurrency Model

| Thread | Owner | Work |
|---|---|---|
| Main | Textual | Async UI loop; `post_message` consumer |
| Capture (per live backend) | `capture/wlr.py` | Owns the Wayland connection and dispatch loop; requests one compositor copy per tick, copies shm pixels into an owned `DisplayFrame`, hands it to the coordinator |
| Worker | `coordinator.py` | Dequeues frames, runs `LuminanceAnalyzer` + `TemporalTracker`, emits metrics via callback → `post_message` |
| Mock timer | `capture/mock.py` | 1 Hz ticker producing synthetic frames |

- **Queue discipline:** `queue.Queue(maxsize=1)` with drop-oldest (dequeue-without-block, then put). A stalled UI never starves the capture buffer pool.
- **Pause (`Space`/`P`):** coordinator stops consuming; capture continues but drops (queue semantics unchanged). Resume continues temporal tracking (previous frame is retained).
- **Shutdown order (owned by `__main__.py`):** signal/`Q` → `coordinator.stop()` → `backend.stop()` (shuts down the Wayland dispatch thread and releases shm pools) → Textual exit → terminal restored. SIGINT and SIGTERM both take this path.

## 6. Error Handling (M6)

| Failure | Behavior |
|---|---|
| Compositor lacks `zwlr_screencopy_manager_v1` (e.g. GNOME/KDE) | Friendly fatal message naming the unsupported compositor, hint to use a wlroots-family compositor |
| `--display` connector not found | `CaptureError` listing available outputs; app stays on picker |
| Capture `failed` event / session lock | Retry with backoff; after 5 consecutive failures → `DisplayDisconnectedError` → banner "Display disconnected — reconnecting…", temporal reset on success |
| Output disappears (unplug) | Same as above; picker re-offers remaining outputs via `[S]` |
| Resolution change | New shm size negotiated automatically; temporal tracker auto-resets (§4) |
| Wayland connect/protocol error | `CaptureError` → banner + friendly fatal |
| SIGTERM/SIGINT | Clean teardown (§5) |

Logging: `logging` to stderr, `WARNING` default, `-v` → `DEBUG`. Nothing else writes to stdout/stderr during normal operation.

## 7. Technology Stack & Packaging

- Runtime: `numpy>=1.26.0`, `textual>=0.80.0`, `pywayland>=0.4.19`.
- Dev: `pytest>=8.0.0`, `ruff>=0.6.0`, `mypy>=1.10.0` (pins consistent everywhere).
- **Protocol bindings:** `openbrightness/due/_proto/` holds pywayland-generated
  bindings for `wlr-screencopy-unstable-v1` (+ core `wayland`), vendored so no
  scanner step is needed at install time. Regenerate with
  `pywayland-scanner -i /usr/share/wayland/wayland.xml protocols/wlr-screencopy-unstable-v1.xml -o openbrightness/due/_proto`.
- `pyproject.toml`: hatchling, PEP 621, `openbrightness-due` v0.1.0, MIT, console script `due = openbrightness.due.__main__:main`.

## 8. Milestones

| # | Objective | Deliverables | Verification |
|---|---|---|---|
| M0 | Scaffold & dependency bridge | `pyproject.toml`, package tree, `.venv` bootstrap | `pip install -e ".[dev]"` succeeds; `import pywayland`, `import numpy`, `import textual` all OK |
| M1 | Models & pure analysis | `models.py`, `analysis/luminance.py`, `temporal/tracker.py`, `tests/test_*` | Synthetic-matrix tests: black/white/gray/gradient/checkerboard pass exact expectations |
| M2 | Discovery, mock capture, coordinator | `discovery.py`, `capture/base.py`, `capture/mock.py`, `coordinator.py`, tests | `test_discovery`/`test_mock_backend`/`test_coordinator` green; streaming without RSS growth |
| M3 | Textual TUI on mock data | `tui/` full tree incl. StatusBanner | `app.run_test()` suite green headless |
| M4 | Live capture backend | `capture/wlr.py`, vendored `_proto/` bindings, `protocols/` XML | Real Niri frames → owned RGB NumPy arrays at expected resolution/stride; **verified live**: 1920×1200 pixels delivered with clean teardown |
| M5 | Integration & display switching | `screens/select.py` wiring, `--display`, `--backend`, `[S]` | Picker→live dashboard; `--display eDP-1` honored natively |
| M6 | Error handling & resilience | Full §6 matrix, signal handling | Unplug/lock/unsupported-compositor scenarios → banner + recovery, no crash |
| M7 | Performance benchmark | `benchmark.py`, `tests/test_perf.py` | 1,000 frames: **total < 25 ms**, analysis < 2 ms, RSS stable |
| M8 | Docs & release | `README.md`, full suite green, `v0.1.0` tag | All acceptance criteria below checked |

## 9. Performance Targets (single source of truth)

| Stage | Target | Measured (Ryzen 5 5625U, 1920×1200) |
|---|---|---|
| T_extract (shm → owned RGB copy + subsample luma) | < 5 ms | ~3.6 ms |
| T_analysis (temporal + metrics, shared luma) | < 2 ms | ~1.4 ms |
| **T_total** | **< 25 ms** | **~5.0 ms** |
| CPU | < 1.0% of one core sustained at 1 FPS | ~0.5% |
| RSS | < 80 MB, zero growth over 1 h soak | stable |

Note: `PLAN.md`'s "T_extract < 0.5 ms" reflected *subsample-only* extraction
(research §7.4). DUE's `DisplayFrame` contract stores a full-resolution owned
RGB copy (PLAN_V1 §2.3), so extract carries a full-frame BGRx→RGB copy cost;
the figure is corrected here to match the contract.

## 10. Acceptance Criteria (V1)

1. `due` runs on Fedora/Niri without crashes and without elevated privileges.
2. Discovers all active outputs; TUI picker and `--display <connector>` both work (native connector selection).
3. Live ~1 FPS capture via `WlrScreencopyBackend` on Niri.
4. Metrics match synthetic ground truth within tolerance: mean/median/P10/P90 error ≤ 0.5/255 on uniform frames; dark/bright ratios exact on bimodal fixtures; RMS contrast exact on gray ramps.
5. In-place Textual dashboard: metric cards, live 64-bin histogram, telemetry footer, error banner.
6. `[Space]/[P]` pause, `[S]` switch display, `[R]` reset temporal, `[Q]` quit — all functional.
7. **Zero image/framebuffer files written to disk.**
8. Test suite passes under pytest; analyzer and tracker are fully covered by synthetic-frame tests (no live session needed for CI).
9. End-to-end latency < 25 ms and CPU < 1.0% on target hardware (Ryzen 5 5625U, 1920×1200).
10. Clean shutdown on SIGINT/SIGTERM/`[Q]`: terminal restored, Wayland connection and shm pools released.

## 11. Risks

| Risk | Mitigation |
|---|---|
| zwlr_screencopy unavailable (GNOME/KDE) | Clear fatal error naming the protocol; portal-based capture tracked for V1.1 once the pipewiresrc DMA-BUF bug is fixed (§0.A) |
| Large-frame copy cost (1920×1200×4 shm → RGB) | Compositor does the slow part; our copy is a single stride-aware vectorized op (~1 ms class), well inside budget |
| Session lock / compositor restart | `failed` events retried with backoff; `DisplayDisconnectedError` surfaces in the banner; `[S]` re-offers outputs |
| Fractional scaling | Capture is the physical framebuffer; analysis reflects physical pixels |
| Textual threading bugs | All UI mutation via `post_message`; worker never touches widgets |
| HDCP/protected content blacks | Metrics will read ~0 during protected playback; banner notice on sustained black frames (outlier heuristic) |
| Future DDC/CI (V3) EEPROM wear | Constraint recorded now: deadband ≥ 5%, ≤ 1 write / 10–15 s, smoothing — see `linux_display_control_report.md` §3.8 |

## 12. V2/V3 Boundary (policy)

- **V2:** laptop `eDP-1` backlight only — volatile PWM via `org.freedesktop.login1.Session.SetBrightness`, never `/sys` writes.
- **V3:** external monitor DDC/CI **considered** per IDEA.md §7 with mandatory rate-limiting and EEPROM write-dampening (§11 last row). Any V3 plan must pass the research report's §3.8 safety rules before code is written.
