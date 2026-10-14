# OpenBrightness — Display Understanding Engine (DUE)

A local, terminal-based, strictly read-only display perception engine for Linux/Wayland.

DUE captures ~1 frame per second from a selected monitor, computes luminance, contrast,
and temporal statistics with vectorized NumPy, and renders a live in-place Textual
dashboard.

## Principles

- **Read-only** — no DDC/CI writes, no backlight writes, ever.
- **Zero image I/O** — no screenshots or framebuffers are written to disk.
- **Quiet** — no log spam; `-v` enables debug output.

## Requirements

- Linux with a Wayland compositor that supports `zwlr_screencopy_manager_v1`
  (niri and sway verified/expected; **GNOME/KDE are not supported in V1** — see
  `PLAN_V1.md` §0.A for the capture-architecture rationale)
- Python 3.12+
- `wayland` core protocol XML (`/usr/share/wayland/wayland.xml`, from `wayland` or
  `wayland-devel`) — needed only if you regenerate the vendored protocol bindings

## Install

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

```sh
due                    # interactive display picker + dashboard
due --display eDP-1    # capture a specific connector
due --backend mock     # synthetic frames (no session needed)
due --list-outputs     # enumerate active outputs
```

Keys: `Space`/`P` pause · `S` switch display · `R` reset temporal stats · `Q` quit.

## How capture works

DUE requests one frame per tick via `zwlr_screencopy_manager_v1`: the compositor
copies the output into a shared-memory (`wl_shm`) buffer that DUE owns, and DUE
converts the pixels into an owned RGB NumPy array. No GPU buffers, no DMA-BUF
imports — plain CPU memory end to end. Protocol bindings are vendored under
`openbrightness/due/_proto/` (regenerate with `pywayland-scanner`, see
`PLAN_V1.md` §7).

## Testing

### 1. Automated test suite (no display session needed)

```sh
source .venv/bin/activate
pytest
```

88 tests cover the data models, analysis math, temporal tracking, output
discovery, mock capture, the wlr capture logic, the threaded coordinator, the
TUI (headless), the CLI, error handling, and performance smoke checks. Tests
that need a live Wayland session (in `tests/test_live_capture.py`) auto-skip
when run outside one, so this works over SSH and in CI.

Run a single area while iterating, e.g.:

```sh
pytest tests/test_analysis.py -v      # statistics math against synthetic frames
pytest tests/test_tui.py -v           # headless Textual dashboard tests
pytest tests/test_live_capture.py -v  # live capture (only inside a Wayland session)
```

### 2. Try the TUI without any display capture (works anywhere)

```sh
due --backend mock
```

This streams deterministic synthetic frames (gradient/checkerboard/sweep) at
1 FPS into the full dashboard. Exercise every control:

1. Watch the metric cards and 64-bin histogram update once per second.
2. Press `Space` (or `P`) — telemetry footer flips to `PAUSED`; press again to resume.
3. Press `R` — "Temporal statistics reset" appears in the status banner;
   `temporal Δ` shows `—` for one frame.
4. Press `S` — returns to the display picker; arrow keys + Enter select a display.
5. Press `Q` — clean exit; the terminal is fully restored.

### 3. Live capture on your own display (niri/sway session)

```sh
due --list-outputs          # 1. verify both monitors are discovered
due --display eDP-1         # 2. capture a specific connector
due                         # 3. or start with the interactive picker
```

Sanity-check the numbers: pointing the dashboard at a mostly-white window should
push `mean` high and `bright (>204)` up; a dark terminal should push `dark (<51)`
up. `temporal Δ` should be ~0 on a static screen and rise while content moves.

Failure paths worth trying:

- `due --display NONSENSE` → lists the available connectors and exits 1.
- `due --backend mock --display eDP-1` → mock ignores the connector (documented).

### 4. Live capture tests (inside a Wayland session)

```sh
pytest tests/test_live_capture.py -v
```

Verifies real frames arrive at the panel's physical resolution with clean
teardown, and that a missing connector produces a proper `CaptureError`.

### 5. Performance benchmark

```sh
python -m openbrightness.due.benchmark              # 1,000 frames @ 1920x1200
python -m openbrightness.due.benchmark --frames 100 --width 2560 --height 1440
```

Prints per-stage latency (extract / analysis / total) and RSS growth; exits
non-zero if analysis ≥ 2 ms mean or total ≥ 25 ms mean (PLAN_V1.md §9).
Reference numbers (Ryzen 5 5625U, 1920×1200): extract ~4 ms, analysis ~1.4 ms,
total ~5.4 ms per frame at 1 FPS.

### 6. Code quality gates

```sh
ruff check openbrightness tests   # lint
mypy openbrightness               # strict type-check
```

## Documentation

- `PLAN_V1.md` — authoritative V1 implementation plan
- `IDEA.md` — product concept and roadmap
- `docs/research/` — capture and display-control research reports

## License

MIT — see `LICENSE`.
