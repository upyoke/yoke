"""Stable executable path of a served-release relay."""
from pathlib import Path

RELAY_LAUNCH_LINK_NAME = "venv"


def relay_launch_path(state_dir: Path) -> Path:
    return Path(state_dir) / RELAY_LAUNCH_LINK_NAME


def relay_launch_executable(state_dir: Path) -> Path:
    return relay_launch_path(state_dir) / "bin" / "yoke"

