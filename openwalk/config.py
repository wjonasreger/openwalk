"""Configuration management for OpenWalk.

Loads and saves user settings from ~/.openwalk/config.toml.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from openwalk.session.calories import UserProfile

CONFIG_DIR = Path.home() / ".openwalk"
CONFIG_PATH = CONFIG_DIR / "config.toml"

DEFAULT_CONFIG: dict[str, Any] = {
    "user": {
        "weight_lbs": 275.0,
        "height_inches": 67.0,
        "age_years": 29,
        "gender": "male",
    },
    "display": {
        "sparkline_minutes": 15,
    },
}

# TOML template for config init (tomllib is read-only, so we write manually)
_CONFIG_TEMPLATE = """\
# OpenWalk configuration
# https://github.com/wjonasreger/openwalk

[user]
weight_lbs = {weight_lbs}
height_inches = {height_inches}
age_years = {age_years}
gender = "{gender}"

[display]
sparkline_minutes = {sparkline_minutes}
"""


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load config from TOML file, merging with defaults.

    Returns defaults if file doesn't exist or is invalid.
    """
    config: dict[str, Any] = {section: dict(values) for section, values in DEFAULT_CONFIG.items()}

    if path.exists():
        try:
            with open(path, "rb") as f:
                user_config = tomllib.load(f)
            # Merge user config into defaults (one level deep)
            for section, values in user_config.items():
                if section in config and isinstance(values, dict):
                    config[section].update(values)
                else:
                    config[section] = values
        except (tomllib.TOMLDecodeError, OSError):
            pass  # Fall back to defaults

    return config


def save_config(config: dict[str, Any], path: Path = CONFIG_PATH) -> None:
    """Save config to TOML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    user = config.get("user", DEFAULT_CONFIG["user"])
    display = config.get("display", DEFAULT_CONFIG["display"])
    content = _CONFIG_TEMPLATE.format(
        weight_lbs=user["weight_lbs"],
        height_inches=user["height_inches"],
        age_years=user["age_years"],
        gender=user["gender"],
        sparkline_minutes=display.get("sparkline_minutes", 15),
    )
    path.write_text(content)


def config_to_profile(config: dict[str, Any]) -> UserProfile:
    """Build a UserProfile from the config dict."""
    user = config.get("user", DEFAULT_CONFIG["user"])
    return UserProfile(
        weight_lbs=float(user.get("weight_lbs", 275.0)),
        height_inches=float(user.get("height_inches", 67.0)),
        age_years=int(user.get("age_years", 29)),
        gender=str(user.get("gender", "male")),
    )


def format_config(config: dict[str, Any]) -> str:
    """Format config for display."""
    lines: list[str] = []
    for section, values in config.items():
        lines.append(f"[{section}]")
        if isinstance(values, dict):
            for key, val in values.items():
                lines.append(f"  {key} = {val}")
        lines.append("")
    return "\n".join(lines)
