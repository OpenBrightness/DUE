"""Auto-adjust state persistence (PLAN.md 11.3): a tiny flat TOML file.

``~/.config/openbrightness/due.toml`` stores only user preferences and the
baseline captured at enable time. ``tomllib`` reads; writes are a minimal
hand-rolled serializer (stdlib has no TOML writer).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

CONFIG_DIR = "openbrightness"
CONFIG_NAME = "due.toml"


@dataclass(frozen=True, slots=True)
class AutoAdjustConfig:
    """Persisted settings. ``baseline`` is None until auto is first enabled."""

    auto_enabled: bool = False
    baseline: float | None = None
    factor_min: float = 0.6
    alpha: float = 0.2
    motion_freeze_threshold: float = 0.05

    def validate(self) -> None:
        if not 0.0 < self.factor_min <= 1.0:
            raise ValueError(f"factor_min must be in (0, 1], got {self.factor_min}")
        if not 0.0 < self.alpha <= 1.0:
            raise ValueError(f"alpha must be in (0, 1], got {self.alpha}")
        if self.motion_freeze_threshold < 0.0:
            raise ValueError("motion_freeze_threshold must be >= 0")
        if self.baseline is not None and not 0.0 <= self.baseline <= 1.0:
            raise ValueError(f"baseline must be in [0, 1], got {self.baseline}")


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(Path.home(), ".config")
    return Path(base) / CONFIG_DIR / CONFIG_NAME


def load_config(path: Path | None = None) -> AutoAdjustConfig:
    """Load settings; missing/invalid file yields safe defaults (auto OFF)."""
    config_path = path or default_config_path()
    try:
        with config_path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return AutoAdjustConfig()
    kwargs: dict[str, object] = {}
    for f in fields(AutoAdjustConfig):
        if f.name in data:
            kwargs[f.name] = data[f.name]
    config = AutoAdjustConfig(**kwargs)  # type: ignore[arg-type]
    try:
        config.validate()
    except ValueError:
        return AutoAdjustConfig()
    return config


def save_config(config: AutoAdjustConfig, path: Path | None = None) -> None:
    config.validate()
    config_path = path or default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"auto_enabled = {'true' if config.auto_enabled else 'false'}",
        f"factor_min = {config.factor_min}",
        f"alpha = {config.alpha}",
        f"motion_freeze_threshold = {config.motion_freeze_threshold}",
    ]
    if config.baseline is not None:
        lines.append(f"baseline = {config.baseline}")
    config_path.write_text("\n".join(lines) + "\n")
