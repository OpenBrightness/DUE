# LEARNING — OpenBrightness DUE

> [!abstract] What this is
> Engineering knowledge base for DUE: everything implemented, every formula, and **why** each decision was made. Companion to [[PLAN.md]] (what) and `docs/research/` (evidence).
>
> Stack: Python 3.12 · NumPy · Textual 8.2.8 · pywayland · systemd-logind
> Status: **V1 done** (160 tests, live-verified on Fedora 44 / Niri 26.04) · **V2 done** (auto-adjust)

---

## 1. Architecture in one glance

```
zwlr_screencopy (compositor copies → wl_shm)
   → bgrx_to_rgb (owned RGB ndarray)
   → coordinator.Queue(maxsize=1, drop-oldest)
   → worker: frame_luma → [TemporalTracker + LuminanceAnalyzer] → LuminanceMetrics
   → TUI (post_message)  ──►  ControlManager → policy → safety gate → logind SetBrightness
```

- **Decoupling rule:** `control/*` imports only `models` + stdlib. Capture/analysis never know control exists. Only `tui/app.py` wires them. *(Research §8.1: perception must never depend on actuation.)*
- Threads: Textual main · capture (owns Wayland connection) · coordinator worker · control write worker.

---

## 2. Capture — why zwlr_screencopy + wl_shm

> [!warning] The pivot that saved V1
> The planned GStreamer/PipeWire path is **broken on this stack**: `pipewiresrc` 1.6.8 fails to fixate caps against niri's DRM modifier list and delivers **1-byte placeholder buffers** — reproduced across every workaround. GStreamer would have shipped a silently empty analyzer.

| Path | Verdict | Reason |
|---|---|---|
| GStreamer `pipewiresrc` | ❌ dropped | DMA-BUF buffers unmappable (empirical, 2026-10-14) |
| `zwlr_screencopy_manager_v1` | ✅ adopted | compositor copies into client `wl_shm` = plain CPU RAM |
| xdg portal | ⏳ deferred | same GStreamer bug underneath; portability path when fixed |

- **Cursor excluded:** `capture_output(overlay_cursor=0)` — a cursor dot would skew luminance.
- **Owned copies, never views:** strided views into shm/DMA memory die at unmap. `DisplayFrame.data` is C-contiguous and owned; `get_subsampled()` returns a *copy*. This kills an entire class of use-after-free bugs.
- **Vendor `_proto/` bindings** so installs need no protocol scanner. `protocols/*.xml` is the source of truth.

---

## 3. Analysis formulas

### 3.1 BT.709 luma — the base signal

$$Y = 0.2126\,R + 0.7152\,G + 0.0722\,B$$

- Float32, output in 0–255. Rec.709/sRGB luminance — the perceptual "how bright is this pixel" that every other metric builds on.
- Validated against integer approx $(54R + 183G + 19B) \gg 8$ — max error < 0.4/255. Float kept for accuracy; cost negligible.

### 3.2 4× strided subsample

$$Y_{sub} = Y[::4,\ ::4] \quad (1920{\times}1200 \rightarrow 480{\times}300)$$

- **22× speedup**, < 0.08% mean-luminance error (statistics are spatially redundant).
- Implemented as **one gather+luma pass** (`frame_luma`) — the arithmetic writes compact output, so no intermediate copy. This killed a 2× duplicate computation bug: tracker and analyzer share one luma array per frame.

### 3.3 Descriptive statistics

| Metric | Formula | Why it exists |
|---|---|---|
| Mean | $\bar{Y} = \frac{1}{N}\sum Y_i$ | content "brightness" — primary V2 policy input |
| Percentiles | $P_{10}, P_{50}, P_{90}$ via one `np.partition` pass | robust spread; median = P50 (deduplicated from an earlier double definition) |
| Dark ratio | $R_d = \frac{1}{N}\sum \mathbb{I}(Y_i < 51)$ | dark-UI/night dominance (20% of range) |
| Bright ratio | $R_b = \frac{1}{N}\sum \mathbb{I}(Y_i > 204)$ | glare: white documents (80% of range) |
| RMS contrast | $C_{RMS} = \sigma_Y \in [0, 127.5]$ | scene harshness; classic psychophysical contrast |
| Temporal delta | $\Delta = \frac{1}{255}\cdot\frac{1}{N}\sum \|Y_{i,t} - Y_{i,t-1}\|$ | motion detection (video guard) |
| Histogram | $h[k] = \frac{1}{N}\,\mathrm{count}(Y \in \mathrm{bin}_k)$, 64 bins | distribution shape for tuning |

- Percentiles via `np.partition` (≈1 ms) instead of `np.percentile` (≈1.05 ms × 3 internal passes). Histogram via `np.bincount` (≈0.15 ms) vs `np.histogram` (≈0.8 ms). **Same results, ~3× faster** — these two swaps moved analysis from 4.3 ms → 1.4 ms.
- Canonical RMS range is **0–127.5** (σ of Y on 0–255); TUI shows $C_{RMS}/127.5$ for readability.

### 3.4 Motion tag thresholds (display only)

| Δ | Tag |
|---|---|
| ≤ 0.005 | Static |
| ≤ 0.05 | Light motion |
| > 0.05 | Active motion |

> [!note] "Typing" was rejected as a label — temporal delta cannot distinguish typing from scrolling. Honesty in UI wording: only claim what the engine measures.

---

## 4. Temporal tracker

- First frame / reset / resolution change → $\Delta = $ `None` (never fake 0).
- Shape change silently rebases (stores current as previous) — mode switches must not crash.
- `reset()` (`R`) drops previous frame + history; trends clear too.

---

## 5. V2 Auto-adjust — policy formulas

**Design goal:** reduce eye strain from residual backlight glow during dark content. Dim-only: never exceed what the user set.

### 5.1 Content "need for light"

$$S = 0.6\cdot\frac{\bar{Y}}{255} + 0.4\,(1 - R_d) \in [0, 1]$$

- Mean luminance weighted 60/40 with inverse dark-ratio. Bright content → S→1 (needs full backlight); dark content → S→0 (needs little).

### 5.2 Dim-only target

$$\text{target} = \text{baseline} \cdot \big(F_{min} + (1 - F_{min})\,S\big), \quad F_{min} = 0.6$$

- **Invariant: target ≤ baseline.** White screen = your baseline (restoration, not boost). Black screen = 60% of baseline floor.
- All values normalized 0–1 of `max_brightness` (65535 raw steps on `amdgpu_bl1`).

### 5.3 EMA smoothing

$$\text{ema}_t = \alpha\,\text{target} + (1-\alpha)\,\text{ema}_{t-1}, \quad \alpha = 0.2$$

- ~5–15 s convergence at 1 FPS. Smooth by design: instant content→brightness translation = visible pumping. This is the anti-annoyance formula.

### 5.4 Safety gate (applied to every write)

| Gate | Rule | Why |
|---|---|---|
| Opt-in | auto OFF → **zero writes** | user control; no config = OFF |
| Floor clamp | $\max(0.05,\ F_{min}\cdot\text{baseline}) \le \text{target} \le \text{baseline}$ | never blackout panel (0% = unusable); never exceed user setting |
| Motion freeze | $\Delta > 0.05 \Rightarrow$ hold | dimming during video is distracting |
| Deadband | $\|\text{target} - \text{applied}\| \ge 0.03\cdot\text{baseline}$ | sub-threshold writes are invisible but annoying |
| Rate limit | ≥ 2 s between writes | anti-flicker (internal is EEPROM-safe but eyes aren't) |
| Override inhibit | drift $> 2\%$ after 2 s settle → stand down 300 s, adopt user value as baseline | "user intent supersedes" (research §10.3) |
| **External = never** | no control backend is even instantiated | DDC/CI writes hit EEPROM: 10k–100k cycles → 1 write/s bricks a monitor in days |

> [!danger] The EEPROM invariant is architectural, not conventional
> Routing is gated on `OutputInfo.is_internal` (eDP/LVDS/DSI). The 10k-frame soak test asserts `ledger.count("HDMI-A-1") == 0`. Safety you can prove > safety you promise.

### 5.5 Baseline semantics

- `baseline` = brightness **at the moment auto was enabled** (or re-captured after manual override). It is the policy's ceiling.
- **Exit keeps current brightness** (deliberate deviation from research §10.2 — quitting at night must not blind you). Restore happens only on explicit toggle-OFF.

---

## 6. Formulas that keep the TUI honest

| Formula | Where | Purpose |
|---|---|---|
| Bar fill $= \mathrm{round}\big(\frac{v}{v_{max}} \cdot w\big)$ | metric gauges | value → glyphs |
| Largest-remainder rounding | composition bar (D/M/B) | segments **always sum to width** — plain `round()` overflows |
| Peak norm $= \frac{h[k]}{\max h} \cdot \mathrm{rows}$ | multi-line histogram | "% of peak" axis (labeled as such — plain "%" would lie) |
| Bin grouping $g = \lceil 64 / w \rceil$, sum groups | narrow terminals | histogram degrades instead of overflowing |
| Label merge when $\mathrm{col}_{next} < \mathrm{col} + \mathrm{len} + 1$ | P10/P50/P90 markers | no glyph collision |
| Sparkline pinned scale: 255 (luma), 1.0 (delta) | trend widget | auto-scaling would amplify noise to full height |

---

## 7. Performance — measured (1920×1200, Ryzen 5 5625U)

| Stage | Target | Measured |
|---|---|---|
| extract (shm→RGB + luma) | < 5 ms | ~4 ms |
| analysis (shared luma) | < 2 ms | ~1.4 ms |
| **total** | **< 25 ms** | **~5.5 ms** |
| CPU @ 1 FPS | < 1% | ~0.5% |

Wins, in order of impact: **shared luma** (removed 2× duplicate) → **partition/bincount** → **slice-assignment channel swap** (fancy `[:, :, 2::-1].copy()` benchmarks ~6× slower) → buffer reuse.

---

## 8. Hard-won lessons (the scar tissue)

> [!bug] Environment & library traps that cost real debugging time

1. **Silent failure > loud failure.** pipewiresrc delivered 1-byte buffers *successfully*. Test with pixel assertions, not just "frames arrived".
2. **DOM timing races in Textual.** Metrics messages arrive before children mount; `Query.first()` raises on empty. Fix: non-raising `next(iter(query(...)), None)` lookup — used uniformly in `DashboardScreen`.
3. **Textual 8.2.8 has no `@media`.** Responsive stacking = `on_resize` toggling `.-narrow` classes in Python. And `align: center middle` **clips the top** of overflowing content → "auto-center + safe scroll" (align top when content > viewport).
4. **Method-name collision:** `Widget._render_content()` is a framework hook; my override crashed rendering. Textual's API surface is large — grep base classes before naming.
5. **Rich markup eats `[Internal]`.** Labels parse `[...]` as style tags. `Label(..., markup=False)` for literal text.
6. **AMD brightness quirk:** `brightness` (43528) and `actual_brightness` (35185) are **different scales** (`scale: non-linear`). Comparing writes against the wrong file falsely triggered the 5-min override inhibit within seconds. Fix: read the **setpoint** file (`brightness`) — same domain as our writes *and* Fn-key writes.
7. **Status must emit every tick.** Emitting only on writes froze the TUI strip through every deadband/inhibit early-return — the policy was working invisibly.
8. **FUSE mount lies about permissions** (0777, chmod ignored) → ruff `EXE002` disabled with an explanatory comment. Environment bugs need documenting, not fighting.
9. **pywayland GC teardown:** un-destroyed proxies free after `display.disconnect()` → SIGSEGV at exit. Explicit `destroy()` on every proxy in `finally`; cleanup must run on *all* paths including early raises.
10. **`np.partition` defaults to the last axis** on 2-D input. Flatten first when computing global quantiles.
11. **Mock frames must never drive real hardware.** `--backend mock` refuses persisted `auto_enabled=true`; explicit `[A]` still allowed. Synthetic data writing physical registers is a footgun.

---

## 9. Testing philosophy

- **160 tests, zero hardware in CI.** Everything injectable: fake clock (rate-limit/inhibit tests), fake D-Bus (call-shape assertion `("backlight", dev, u)` — the live-verified logind signature), fake sysfs tree (`tmp_path`), monkeypatched logind fallback (so tests *cannot* touch real brightness).
- **Deterministic soak:** 10k synthetic metric frames → assert writes ⊆ [floor, baseline], external count == 0. The V2-M5 "1-hour soak" requirement, made reproducible.
- **Boundary tests** for every threshold (motion tags, factor clamps, deadband, inhibit expiry).
- Live tests (`test_live_capture.py`) auto-skip without `WAYLAND_DISPLAY` — same suite works over SSH and in CI.
- UI contracts guarded: exact string formats (`128.00`) preserved so tests catch layout regressions.

---

## 10. Known limitations & next steps

| Limitation | Why | Where it's solved |
|---|---|---|
| White page at night still glares | content-only analysis can't tell 2 PM from midnight | V3: ambient light sensor (`iio-sensor-proxy`) as policy input |
| $0.6$ floor / $\alpha=0.2$ are judgment defaults | no user study yet | `PolicyConfig` + `due.toml` are the tuning seams |
| Raw-step fractions ≠ perception | `scale: non-linear` on AMD | perceptual mapping is a V2.x candidate |
| GNOME/KDE unsupported | no zwlr_screencopy there; portal path blocked by the GStreamer bug | revisit when pipewiresrc is fixed upstream |
| External manual DDC (V2-M4) | deliberately deferred; rate limits already specified (deadband ≥ 5%, ≤ 1 write/10–15 s) | next plan |
| Glare mode (dim *bright* content) | alternative policy, trades daylight readability | small change in `_raw_target`; config-selectable candidate |

---

## 11. One-line principles

> [!tip] The compressed version
> 1. **Measure truthfully, act conservatively** — metrics are pure; actuation is gated, clamped, deadbanded, and always reversible-by-user.
> 2. **Owned memory or nothing** — copies beat dangling views.
> 3. **Share computed intermediates** — luma once per frame.
> 4. **Safety belongs in the policy layer, not the UI** — externals can't be auto-written even by a buggy caller.
> 5. **Defaults that fail safe** — OFF, floor 5%, keep-on-exit, user intent wins.
> 6. **Verify against real hardware early** — every silent-bug above was found by running it.
