"""Config persistence tests (PLAN.md 11.3) — tmp_path only."""

from __future__ import annotations

from pathlib import Path

from openbrightness.due.control.config import AutoAdjustConfig, load_config, save_config


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "due.toml"
    config = AutoAdjustConfig(
        auto_enabled=True, baseline=0.87, factor_min=0.7, alpha=0.3,
        motion_freeze_threshold=0.1,
    )
    save_config(config, path)
    loaded = load_config(path)
    assert loaded == config


def test_defaults_when_missing(tmp_path: Path) -> None:
    config = load_config(tmp_path / "missing.toml")
    assert config == AutoAdjustConfig()
    assert config.auto_enabled is False  # opt-in default (11.6 invariant 2)


def test_invalid_file_yields_defaults(tmp_path: Path) -> None:
    path = tmp_path / "due.toml"
    path.write_text("this is { not toml")
    assert load_config(path) == AutoAdjustConfig()


def test_invalid_values_yield_defaults(tmp_path: Path) -> None:
    path = tmp_path / "due.toml"
    path.write_text("factor_min = 5.0\n")
    assert load_config(path) == AutoAdjustConfig()


def test_baseline_omitted_when_none(tmp_path: Path) -> None:
    path = tmp_path / "due.toml"
    save_config(AutoAdjustConfig(auto_enabled=False), path)
    text = path.read_text()
    assert "baseline" not in text
    assert "auto_enabled = false" in text


def test_validate_rejects_out_of_range() -> None:
    for bad in (
        AutoAdjustConfig(factor_min=0.0),
        AutoAdjustConfig(alpha=1.5),
        AutoAdjustConfig(motion_freeze_threshold=-1.0),
        AutoAdjustConfig(baseline=2.0),
    ):
        try:
            bad.validate()
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad}")
