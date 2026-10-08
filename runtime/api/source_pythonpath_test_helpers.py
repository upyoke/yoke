"""Source-tree import path helpers for subprocess tests."""

from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_NAMES = (
    "yoke-core",
    "yoke-contracts",
    "yoke-cli",
    "yoke-harness",
)
PACKAGE_ROOT = REPO_ROOT / "packages"
SOURCE_PYTHONPATH = os.pathsep.join(
    str(path)
    for path in (
        REPO_ROOT,
        *(PACKAGE_ROOT / package_name / "src" for package_name in PACKAGE_NAMES),
    )
)


def provision_stub_environment(root: Path) -> Path:
    """A real isolated locked virtual project, without indexes or dependencies."""
    (root / "pyproject.toml").write_text(
        '[project]\nname="source-fixture"\nversion="0.0.0"\n'
        'requires-python=">=3.11"\ndependencies=[]\n[tool.uv]\npackage=false\n'
    )
    venv.EnvBuilder(with_pip=False).create(root / ".venv")
    subprocess.run(
        ["uv", "lock", "--offline", "--python", sys.executable],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return root / ".venv/bin/python3"


__all__ = ["REPO_ROOT", "SOURCE_PYTHONPATH"]
