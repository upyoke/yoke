"""Stable executable path of a served-release relay."""
from pathlib import Path
import sys

RELAY_LAUNCH_LINK_NAME = "venv"


def relay_launch_path(state_dir: Path) -> Path:
    return Path(state_dir) / RELAY_LAUNCH_LINK_NAME


def relay_launch_executable(state_dir: Path) -> Path:
    return relay_launch_path(state_dir) / ("Scripts/yoke.cmd" if sys.platform == "win32" else "bin/yoke")


def relay_venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def relay_venv_executable(root: Path) -> Path:
    return root / ("Scripts/yoke.exe" if sys.platform == "win32" else "bin/yoke")
