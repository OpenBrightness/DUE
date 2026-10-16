"""Display-control layer (V2): content-adaptive backlight adjustment.

Safety-first by design: see PLAN.md section 11. External monitors are never
auto-adjusted (11.2); auto is opt-in and defaults to OFF.
"""

from openbrightness.due.control.base import (
    BacklightUnavailableError,
    ControlError,
    ControlWriteError,
    DisplayControlBackend,
    WriteLedger,
)
from openbrightness.due.control.config import AutoAdjustConfig, load_config, save_config
from openbrightness.due.control.logind import LogindBacklightBackend, discover_backlight_device
from openbrightness.due.control.manager import ControlManager, ControlStatus
from openbrightness.due.control.policy import AdaptiveBrightnessPolicy, PolicyConfig

__all__ = [
    "AdaptiveBrightnessPolicy",
    "AutoAdjustConfig",
    "BacklightUnavailableError",
    "ControlError",
    "ControlManager",
    "ControlStatus",
    "ControlWriteError",
    "DisplayControlBackend",
    "LogindBacklightBackend",
    "PolicyConfig",
    "WriteLedger",
    "discover_backlight_device",
    "load_config",
    "save_config",
]
