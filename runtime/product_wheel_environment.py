"""Isolated native process environment for installed product wheel tests."""

import os
from pathlib import Path
import shutil

from yoke_contracts.venv_layout import venv_scripts

BASE_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def product_env(
    machine_home: Path,
    venv_dir: Path,
    *,
    extra_path: Path | None = None,
) -> dict[str, str]:
    uv = shutil.which("uv")
    assert uv, "uv is an installer prerequisite"
    path_parts = [str(venv_scripts(venv_dir)), str(Path(uv).parent)]
    if extra_path is not None:
        path_parts.append(str(extra_path))
    path_parts.append(os.environ.get("PATH", "") if os.name == "nt" else BASE_PATH)
    return {
        **{key: os.environ[key] for key in ("SYSTEMROOT", "COMSPEC", "PATHEXT", "TEMP", "TMP") if key in os.environ},
        "HOME": str(machine_home.parent),
        "USERPROFILE": str(machine_home.parent),
        "APPDATA": str(machine_home.parent / "AppData" / "Roaming"),
        "LOCALAPPDATA": str(machine_home.parent / "AppData" / "Local"),
        "PATH": os.pathsep.join(path_parts),
        "XDG_BIN_HOME": str(venv_scripts(venv_dir)),
        "UV_TOOL_BIN_DIR": str(venv_scripts(venv_dir)),
        "SHELL": "/bin/bash",
        "YOKE_MACHINE_HOME": str(machine_home),
        "PYTHONNOUSERSITE": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }

