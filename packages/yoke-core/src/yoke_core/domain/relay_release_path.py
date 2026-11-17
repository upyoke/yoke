"""Stable executable path of a served-release relay."""
from pathlib import Path
from yoke_contracts.venv_layout import venv_python, venv_console_script

RELAY_LAUNCH_LINK_NAME = "venv"


def relay_launch_path(state_dir: Path) -> Path:
    return Path(state_dir) / RELAY_LAUNCH_LINK_NAME


def relay_launch_executable(state_dir: Path) -> Path:
    return venv_console_script(relay_launch_path(state_dir), "yoke", windows_suffix=".cmd")


def relay_venv_python(root: Path) -> Path:
    return venv_python(root)


def relay_venv_executable(root: Path) -> Path:
    return venv_console_script(root, "yoke")
