# OpenBrightness — Project Plan (`PLAN.md`)

**Project:** OpenBrightness — Display Understanding Engine (DUE)
**Document Type:** Single authoritative project plan (V1 as-built + V2 design + V3 outlook)
**Target Platform:** Fedora Linux 44 (x86_64), Niri Wayland Compositor (26.04), Linux Kernel 7.1.x
**Target Hardware:** Laptop internal display (`eDP-1` via AMDGPU) & external HDMI/DP monitors
**Status:** **V1 complete & verified (2026-10-15)** — V2 (adaptive adjustment) designed below
**References:**
- Vision & scope: [`IDEA.md`](IDEA.md)
- Capture research: [`docs/research/wayland_pipewire_capture_report.md`](docs/research/wayland_pipewire_capture_report.md)
- Display-control research: [`docs/research/linux_display_control_report.md`](docs/research/linux_display_control_report.md)

---

## 0. Document History & Empirical Corrections

This file consolidates the former `PLAN.md` (original V1 draft) and `PLAN_V1.md`
(reconciled implementation plan) into one project-wide plan, and records the
corrections made when the design met reality.

| # | Correction | Resolution |
|---|---|---|
| 1 | Monitor selection (`--display`, TUI picker) unsatisfiable via the XDG portal (it shows its own dialog and accepts no connector argument) | **Capture built on `WlrScreencopyBackend`** (`zwlr_screencopy_manager_v1` + `wl_shm`) — native per-connector selection, no dialog (see §0.A) |
| 2 | Latency contradiction ("<5 ms" vs "<25 ms") | Single target: **total pipeline < 25 ms** end-to-end at 1 FPS |
| 3 | `discovery` module mandated but missing from file tree/milestones | `openbrightness/due/discovery.py` delivered (M2) |
| 4 | "Zero-copy" subsample views unsafe after buffer unmap; ndarray construction ignoring rowstride | `DisplayFrame` stores a full-res **owned** RGB copy; `get_subsampled()` returns a contiguous copy (deliberate) |
| 5 | `median_luminance` and `p50_luminance` duplicated | Single `median_luminance` (= P50) |
| 6 | "Permanent exclusion" of external control contradicted the vision doc | Restated as a **safety policy**: external monitors are never *auto*-adjusted (EEPROM wear); user-initiated manual adjustment is permitted with mandatory rate limiting (§11.2) |
| 7 | GLib main-loop ownership undefined | Capture backend owns one Wayland dispatch thread (§5) |
| 8 | Error banner promised but undesigned | `StatusBanner` widget delivered (M3) |
| 9 | No `tests/` layout | Full test tree delivered (§2.2) |
| 10 | mypy pin drift | `mypy>=1.10.0` everywhere |
| 11 | "Zero disk I/O" vs config persistence | Precise claim: **zero image/framebuffer I/O** |
| 12 | SIGTERM handling promised, ownerless | `__main__.py` owns SIGINT/SIGTERM (§5) |
| 13 | "Reset history" semantics undefined | `TemporalTracker.reset()` defined (§4) |
| 14 | Cursor exclusion unspecified | `capture_output(overlay_cursor=0)` — cursor never in frames |
| 15 | RMS contrast units drift | Canonical **0–127.5** (σ of Y on 0–255); TUI shows normalized 0–1 |
| 16 | Benchmark geometry mismatched target panel | Benchmarks reference the panel's 1920×1200 (subsample 480×300) |

### 0.A Capture Pivot (Empirical Finding, 2026-10-14)

The original design used GStreamer (`pipewiresrc`) over PipeWire. Live
verification on the target machine (GStreamer 1.28.6 / pipewire-gstreamer 1.6.8)
proved that path **unusable for CPU frame analysis**:

- The Mutter/niri ScreenCast D-Bus flow works, but the PipeWire node it creates
  exposes only `BGRx` with a DRM modifier list; `pipewiresrc` fails to fixate
  caps (`gst_caps_is_fixed` assertion) and delivers **1-byte placeholder
  buffers** — reproduced across every caps-filter workaround.
- `zwlr_screencopy_manager_v1` works perfectly: the compositor copies frames
  into client `wl_shm` memory — plain CPU RAM, exactly what the capture research
  recommends ("prefer linear SHM"). Verified live: 1920×1200 frames with correct
  stride and pixel values.

Consequence: **`WlrScreencopyBackend` is the only live capture backend**, with
vendored pywayland bindings (`_proto/`, source XML in `protocols/`). Cost:
zwlr_screencopy covers niri/sway/wlroots-family compositors but **not GNOME/KDE**
— portal-based portability is deferred until the pipewiresrc DMA-BUF bug is fixed
upstream.

---

## 1. Product Definition & Version Roadmap

DUE is a local, terminal-based display perception engine. It reads what the user
is actually looking at (~1 FPS), turns it into deterministic visual statistics,
and — from V2 on — uses those statistics to gently improve display comfort
(eye-strain reduction) with strict hardware-safety guarantees.

**The arc:** V1 measures and explains. V2 acts on those measurements, safely and
with the user in control.

### 1.1 V1 — Read-Only Perception Engine *(complete, verified)*

A strictly read-only TUI application that surfaces the key metrics needed to
decide *what* display values should change and *why*:

| Metric | What it tells us (and why it matters for comfort) |
|---|---|
| Mean / median / P10 / P90 luminance | How bright the content actually is on screen — the primary signal for target backlight level |
| Dark-pixel ratio (Y < 51) | Dark-IDE / night-time dominance → brightness should likely come down |
| Bright-pixel ratio (Y > 204) | Harsh full-white content → glare reduction candidates |
| RMS contrast (σ of Y) | Overall visual harshness of the scene |
| Temporal delta | Motion on screen — freeze adjustments during video/playback to avoid distraction |
| 64-bin luminance histogram | Distribution shape (skew, bimodality) for policy tuning |
| Capture/analysis latency | Engineering telemetry |

V1 contains **zero actuation logic**: no DDC/CI writes, no backlight writes.

### 1.2 V2 — Adaptive Adjustment Engine *(designed in §11)*

Consumes V1 metrics and adjusts display values to improve the user experience
(brightness/comfort targets derived from measured content). Hard rules:

- **The entire feature is user-toggleable** — auto-adjustment is opt-in
  (default **OFF**), one key press to enable/disable, state persisted.
- **Auto-adjustment targets the laptop internal panel only** (`eDP-*`) —
  volatile GPU/PWM backlight registers, safe for unlimited writes.
- **External monitors are excluded from auto-adjustment** — DDC/CI writes hit
  internal EEPROM rated for 10,000–100,000 write cycles; automated writes would
  destroy the monitor's scaler memory. Externals may only ever be adjusted by
  explicit, user-initiated manual action, with mandatory write rate limiting
  (§11.2).

### 1.3 V3 — Future (out of scope for now)

Content-aware understanding (ML/OCR), ambient light sensors, and further
automation. Any automation for external monitors in any version must remain
**off**; the EEPROM hazard does not expire.

### 1.4 V1 Requirements (delivered)

| # | Requirement | Owner |
|---|---|---|
| R1 | Python 3.12+, strict typing (`mypy --strict`-clean) | all |
| R2 | Linux / Wayland (Fedora + Niri reference target) | — |
| R3 | Monitor selection: interactive TUI picker + `--display <connector>` | `discovery` |
| R4 | Modular capture behind `DisplayCaptureBackend` ABC | `capture` |
| R5 | Fixed ~1 FPS sampling | `capture` |
| R6 | Deterministic vectorized BT.709 statistics | `analysis` |
| R7 | Temporal delta tracking with reset | `temporal` |
| R8 | In-place Textual TUI (no scrollback pollution) | `tui` |
| R9 | **Zero image/framebuffer disk I/O** | all |
| R10 | Zero log spam (quiet default, `-v` for debug) | all |
| R11 | Strictly read-only (V1): no display hardware writes | all |
| R12 | Decoupled pipeline (capture ↛ analysis ↛ UI) | `coordinator` |
| R13 | pytest suite with synthetic-frame fixtures | `tests` |

### 1.5 Non-Goals

- ML/OCR content classification, ambient light sensors, GUI, daemon/REST API (V3+).
- Sandboxed (Flatpak) distribution.
- **Any form of automated adjustment of external monitors — permanently excluded (§11.2).**

---

## 2. Architecture (V1, as built)

### 2.1 Capture

```
                ┌──────────────────────────────┐
 --display / TUI ►      Backend selector       │
                └──────────────┬───────────────┘
                               ▼
                ┌──────────────────────────────┐
                │ WlrScreencopyBackend         │  only live backend
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
                worker thread: shared luma → temporal + metrics
                               │
                               ▼
                Textual UI (post_message)
```

- **wlr path:** `zwlr_screencopy_manager_v1` v3 — one compositor copy per tick
  into our `wl_shm` pool, copied to an owned RGB array, pool recycled. Native
  connector selection, no permission dialog, cursor excluded. Verified live.
- **Mock path:** `MockCaptureBackend` generates deterministic synthetic content
  for TUI development, CI, and `--backend mock`.
- **GStreamer paths:** dropped after live verification (§0.A).

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
│   ├── wlr.py              # zwlr_screencopy + wl_shm (live)
│   └── mock.py             # Synthetic frames
├── analysis/
│   ├── __init__.py
│   └── luminance.py        # LuminanceAnalyzer
├── temporal/
│   ├── __init__.py
│   └── tracker.py          # TemporalTracker
├── benchmark.py            # 1,000-frame harness
└── tui/
    ├── __init__.py
    ├── app.py              # DueApp
    ├── screens/
    │   ├── __init__.py
    │   ├── select.py       # DisplaySelectScreen
    │   └── dashboard.py    # DashboardScreen
    └── widgets/
        ├── __init__.py
        ├── metric_card.py      # LuminanceCard, DistributionCard
        ├── histogram.py        # 64-bin Unicode multi-line spectrum
        ├── trend.py            # TrendWidget: 30-sample sparklines
        └── status_bar.py       # TelemetryFooter + StatusBanner

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
├── test_cli.py             # CLI flags & backend selection
├── test_tui.py
├── test_widgets.py         # widget pure-render tests (histogram/cards/trend)
├── test_error_handling.py  # §6 failure matrix
├── test_perf.py            # benchmark smoke (CI-safe thresholds)
└── test_live_capture.py    # integration; auto-skips without a session
```

### 2.3 Data Contracts

All dataclasses `frozen=True, slots=True`.

**`OutputInfo`** — `connector`, `make`, `model`, `width`, `height`, `refresh_rate`, `is_primary`.
**`DisplayFrame`** — `data: NDArray[uint8] (H,W,3)` RGB, C-contiguous and owned; `width`, `height`, `pts_ns | None`, `captured_monotonic_ns`. `get_subsampled(step=4)` returns a contiguous copy.
**`LuminanceMetrics`** — `mean_luminance`, `median_luminance` (= P50), `p10_luminance`, `p90_luminance`, `dark_ratio` (Y<51), `bright_ratio` (Y>204), `rms_contrast` (0–127.5; TUI shows /127.5), `temporal_delta | None` (0–1), `histogram` (64-bin normalized), `capture_latency_ms`, `analysis_latency_ms`, `width`, `height`, `timestamp_monotonic_ns`.

---

## 3. Analysis Specification

- **Subsampling:** 4× strided subsample (`[::4, ::4]`) computed as one gather+luma pass; 22.2× speedup vs full-res, < 0.08% mean-luminance error. 1920×1200 → 480×300.
- **Luma:** `Y = 0.2126R + 0.7152G + 0.0722B` (float32; verified against integer approximation, max error < 0.4/255).
- **Percentiles:** P10/P50/P90 via a single `np.partition` pass (linear interpolation, `np.percentile`-equivalent).
- **Thresholds:** dark at Y < 51 (20%), bright at Y > 204 (80%).
- **Histogram:** 64 bins over 0–255 via `np.bincount`, normalized to sum 1.
- **Latency:** `T_capture` = PTS→callback (monotonic fallback); `T_analysis` = `perf_counter_ns()` around analysis.
- **Shared luma:** the coordinator computes subsampled luma once per frame and passes it to both the temporal tracker and the analyzer (no duplicate work).

## 4. Temporal Specification

- **Delta:** `temporal_delta = mean(|Y_t − Y_{t−1}|)/255` on subsampled luma; `None` after start/reset/resolution change.
- **Shape change:** tracker silently rebases (stores current as previous) — resolution changes never crash or produce garbage deltas.
- **`reset()`** (`R` key / reconnect): drops previous frame and accumulated history (min/max/mean delta, frame count). Next frame reports `temporal_delta=None`.

## 5. Threading & Concurrency Model

| Thread | Owner | Work |
|---|---|---|
| Main | Textual | Async UI loop; `post_message` consumer |
| Capture | `capture/wlr.py` | Owns the Wayland connection/dispatch loop; one compositor copy per tick → owned `DisplayFrame` → coordinator |
| Worker | `coordinator.py` | Shared luma → temporal + metrics → callback → `post_message` |
| Mock timer | `capture/mock.py` | 1 Hz ticker for synthetic frames |

- **Queue discipline:** `queue.Queue(maxsize=1)`, drop-oldest; a stalled UI never starves capture.
- **Pause (`Space`/`P`):** coordinator stops consuming; capture drops; resume continues temporal tracking.
- **Shutdown (owned by `__main__.py`):** signal/`Q` → `coordinator.stop()` → `backend.stop()` (Wayland thread + shm pools released) → Textual exit → terminal restored. SIGINT and SIGTERM both take this path.

## 6. Error Handling

| Failure | Behavior |
|---|---|
| Compositor lacks `zwlr_screencopy_manager_v1` (e.g. GNOME/KDE) | Friendly fatal naming the unsupported compositor |
| `--display` connector not found | `CaptureError` listing available outputs; app stays on picker |
| Capture `failed` / session lock | Retry with backoff; 5 consecutive failures → `DisplayDisconnectedError` → banner "Display disconnected — reconnecting…", temporal reset on success |
| Output unplug | Same recovery; `[S]` re-offers remaining outputs |
| Resolution change | New shm size negotiated automatically; temporal auto-resets (§4) |
| Wayland connect/protocol error | `CaptureError` → banner + friendly fatal |
| SIGTERM/SIGINT | Clean teardown (§5) |

Logging: `logging` to stderr, `WARNING` default, `-v` → `DEBUG`. Nothing else writes to stdout/stderr during normal operation.

## 7. Technology Stack & Packaging

- Runtime: `numpy>=1.26.0`, `textual>=0.80.0`, `pywayland>=0.4.19`.
- Dev: `pytest>=8.0.0`, `ruff>=0.6.0`, `mypy>=1.10.0`.
- **Protocol bindings:** `openbrightness/due/_proto/` holds pywayland-generated
  bindings (vendored — no scanner step at install). Regenerate with
  `pywayland-scanner -i /usr/share/wayland/wayland.xml protocols/wlr-screencopy-unstable-v1.xml -o openbrightness/due/_proto`.
- `pyproject.toml`: hatchling, PEP 621, `openbrightness-due` v0.1.0, MIT, console script `due`.

## 8. Milestones

### 8.1 V1 (all complete, verified 2026-10-15)

| # | Objective | Status |
|---|---|---|
| M0 | Scaffold, packaging, venv | ✅ |
| M1 | Models + analysis + temporal, synthetic-matrix tests | ✅ |
| M2 | Discovery, mock capture, coordinator | ✅ |
| M3 | Textual TUI on mock data | ✅ |
| M4 | Live capture (`capture/wlr.py`, vendored bindings) — verified live on Niri | ✅ |
| M5 | Integration: CLI `--display`/`--backend`, picker, `[S]` | ✅ |
| M6 | Error-handling matrix, signals, banner | ✅ |
| M7 | 1,000-frame benchmark harness | ✅ |
| M8 | README, full suite green | ✅ |

### 8.2 V2 (adaptive adjustment — see §11)

| # | Objective | Deliverables | Verification |
|---|---|---|---|
| V2-M1 | Control abstraction | `control/base.py` (`DisplayControlBackend` ABC), `control/logind.py` (eDP backlight via `org.freedesktop.login1` `SetBrightness`) | Unit tests with fake D-Bus; brightness read-back matches |
| V2-M2 | Policy engine | `control/policy.py`: metrics → target brightness with deadband, smoothing, motion freeze | Synthetic-metric tests: dark dominance lowers target; temporal delta high → no writes |
| V2-M3 | Toggle & persistence | `[A]` master toggle (auto-adjust on/off, default OFF), config file (`~/.config/openbrightness/due.toml`), TUI status | Toggle flips instantly; state survives restart; OFF means zero writes |
| V2-M4 | Manual adjustment | Rate-limited manual brightness control in TUI (laptop always; external only via explicit user action under §11.2 limits) | Write-rate tests with fake clock: never exceeds limits |
| V2-M5 | Safety soak & docs | Write-count accounting, README + this plan updated | 1-hour soak: external EEPROM writes = 0 when auto on |

## 9. Performance Targets (single source of truth)

| Stage | Target | Measured (Ryzen 5 5625U, 1920×1200) |
|---|---|---|
| T_extract (shm → owned RGB + subsample luma) | < 5 ms | ~4 ms |
| T_analysis (temporal + metrics, shared luma) | < 2 ms | ~1.4 ms |
| **T_total** | **< 25 ms** | **~5.5 ms** |
| CPU | < 1.0% of one core at 1 FPS | ~0.5% |
| RSS | < 80 MB, zero growth over 1 h soak | stable |

Benchmark: `python -m openbrightness.due.benchmark` (exits non-zero above targets).

## 10. Acceptance Criteria

### 10.1 V1 *(all verified 2026-10-15)*

1. ✅ `due` runs on Fedora/Niri without crashes or elevated privileges.
2. ✅ Discovers all active outputs; picker and `--display` both work.
3. ✅ Live ~1 FPS capture via `WlrScreencopyBackend` on Niri.
4. ✅ Metrics match synthetic ground truth (uniform frames ≤ 0.5/255 error; ratios exact on bimodal fixtures; contrast exact on gray ramps).
5. ✅ In-place dashboard: metric cards, 64-bin histogram, telemetry footer, error banner.
6. ✅ `[Space]/[P]` pause, `[S]` switch display, `[R]` reset temporal, `[Q]` quit.
7. ✅ Zero image/framebuffer files written to disk.
8. ✅ Test suite green (88 tests); CI-safe without a live session.
9. ✅ Latency < 25 ms total, CPU < 1.0% on target hardware.
10. ✅ Clean shutdown on SIGINT/SIGTERM/`[Q]`; terminal restored, resources released.

### 10.2 V2

1. Auto-adjustment defaults **OFF**; `[A]` toggles it; state persisted across restarts.
2. With auto ON, **only** the laptop internal panel (`eDP-*`) is ever written; external monitors receive **zero** automatic writes (verified by write-count accounting in a 1-hour soak).
3. Brightness targets derive from V1 metrics (mean/median luminance primary; dark/bright ratios modulate) and are visible in the TUI ("target vs applied").
4. Motion freeze: no adjustments while `temporal_delta` exceeds a threshold (video protection).
5. Manual adjustment honors rate limits even under key-mashing: ≤ 1 write / 10–15 s per display, deadband ≥ 5%.
6. Toggle OFF → zero writes, period. V1 metrics continue to display.
7. All policy math unit-tested with synthetic metrics and a fake clock.

---

## 11. V2 Design — Adaptive Adjustment (safety-first)

### 11.1 Concept

V1 answers "what is the user actually looking at?"; V2 answers "what should the
display be doing about it?". The policy engine translates measured content into a
target backlight level (and later, color temperature), applies it through a
control backend, and shows the user exactly what it did and why. Everything is
opt-in and reversible.

### 11.2 Hardware Safety Policy *(from `linux_display_control_report.md`)*

> [!CAUTION]
> **External monitors are excluded from auto-adjustment — permanently, in every version.**
>
> DDC/CI brightness/contrast writes on external monitors go to internal EEPROM /
> NOR flash rated for **10,000–100,000 write cycles**. An adaptive loop writing at
> even 1 write/minute would exhaust a monitor's EEPROM in weeks-to-months and can
> brick scaler microcode. DisplayPort AUX/USB-C docks additionally drop packets
> and stall scalers. This is a hardware limit, not a software one.

Concretely:

| Display class | Control channel | Auto-adjust | Manual adjust |
|---|---|---|---|
| Laptop internal (`eDP-*`) | `org.freedesktop.login1.Session.SetBrightness` (volatile GPU PWM/DPCD registers) | ✅ allowed (user-toggled) | ✅ allowed |
| External (HDMI/DP/…) | DDC/CI (VESA MCCS over I²C → EEPROM) | ❌ **never** | ✅ allowed, strictly rate-limited |

Mandatory rate limiting for any DDC/CI write path (auto or manual):
- **Deadband:** no write unless |target − applied| ≥ 5%.
- **Rate cap:** ≤ 1 write per 10–15 s per display.
- **Smoothing:** exponential smoothing of targets so inputs never translate 1:1 into writes.
- **Accounting:** every write is logged/countered in-process for test assertions.

### 11.3 Toggle

- `[A]` (and `--auto` flag / config key) toggles auto-adjustment globally.
- Default **OFF** — V1 behavior until the user opts in.
- OFF means the policy engine computes nothing and the control backends issue zero writes; metrics keep streaming.
- TUI shows the auto state and the current "target vs applied" brightness in the status area.

### 11.4 Policy Sketch (deterministic, no ML in V2)

```
target_brightness =
    base
    + w1 * f(mean_luminance)        # bright content → slightly lower backlight
    + w2 * f(dark_ratio)            # dark-UI dominance → lower backlight
    + w3 * f(bright_ratio)          # harsh white → lower backlight
    with motion guard: if temporal_delta > τ: hold
    → EMA smoothing → deadband gate → rate-limited write (laptop only)
```

Weights and curves are constants, tunable from config; all policy behavior is
unit-tested against synthetic metric streams (V1's `MockCaptureBackend` frames
make end-to-end testing possible without touching hardware).

### 11.5 Control Backends (V2)

- **`LogindBacklightBackend`** — the auto path's only backend. `SetBrightness`
  via `org.freedesktop.login1` (session-scoped, no root, < 1 ms). Volatile
  registers: billions of writes are safe — but rate limiting still applies to
  avoid visible flicker/annoyance.
- **`DdcCiBackend`** — manual-only (V2-M4), obeys §11.2 limits unconditionally.
  If safe write budgets cannot be verified for a display, manual DDC/CI degrades
  to "unsupported" rather than guessing.

### 11.6 Invariants (non-negotiable)

1. No code path may auto-adjust an external monitor — enforced by the policy
   layer, not by UI convention.
2. Auto-adjustment is opt-in; absence of config == OFF.
3. Every write goes through the rate limiter; no bypass "just this once".
4. V1 stays usable and correct with all control code disabled (separation
   invariant: perception never depends on actuation).

---

## 12. V3 Outlook (not scheduled)

- Content understanding (OCR/ML) for finer comfort rules; ambient light sensors
  (`iio-sensor-proxy`) as a policy input.
- Color-temperature / night-mode adaptation (compositor-side, safe).
- **Not planned ever:** automated external-monitor adjustment (§11.2 stands).

## 13. Risks

| Risk | Mitigation |
|---|---|
| zwlr_screencopy unavailable (GNOME/KDE) | Clear fatal naming the protocol; portal capture tracked once pipewiresrc's DMA-BUF bug is fixed upstream |
| Large-frame copy cost (1920×1200 BGRx→RGB) | Compositor does the slow part; our copy is one stride-aware vectorized op (~4 ms, inside the 25 ms budget) |
| Session lock / compositor restart | Retries + backoff; banner; `[S]` re-offers outputs |
| Fractional scaling | Capture is the physical framebuffer; metrics reflect physical pixels |
| Textual threading bugs | All UI mutation via `post_message`; workers never touch widgets |
| HDCP/protected content reads ~0 | Notice on sustained black frames |
| **External EEPROM wear** | §11.2 policy: auto never touches externals; manual path rate-limited and accounted |
| V2 policy annoyance (visible pumping) | Motion guard, EMA smoothing, deadband, default OFF |

---

*V1 implementation history: milestones M0–M8 completed and verified 2026-10-14/15;
88 tests green, `ruff`/`mypy --strict` clean, benchmark ~5.5 ms total vs 25 ms
budget, live-verified on Fedora 44 / Niri 26.04. Implementation of V2 should
start with V2-M1.*
