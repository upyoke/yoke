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


_STUB_BACKEND = """\
import base64, hashlib, zipfile

def build_wheel(directory, config=None, metadata=None):
    dist = "source_fixture-0.0.0.dist-info"
    files = {
        dist + "/METADATA": "Metadata-Version: 2.1\\nName: source-fixture\\nVersion: 0.0.0\\n",
        dist + "/WHEEL": "Wheel-Version: 1.0\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n",
    }
    digest = lambda text: base64.urlsafe_b64encode(
        hashlib.sha256(text.encode()).digest()
    ).rstrip(b"=").decode()
    files[dist + "/RECORD"] = "".join(
        f"{path},sha256={digest(text)},{len(text.encode())}\\n"
        for path, text in files.items()
    ) + dist + "/RECORD,,\\n"
    name = "source_fixture-0.0.0-py3-none-any.whl"
    with zipfile.ZipFile(f"{directory}/{name}", "w") as wheel:
        for path, text in files.items():
            wheel.writestr(path, text)
    return name

build_editable = build_wheel
"""


def provision_packaged_stub_environment(root: Path) -> Path:
    """A synced locked project that installs itself, built offline in-tree."""
    (root / "stub_backend.py").write_text(_STUB_BACKEND)
    (root / "pyproject.toml").write_text(
        '[project]\nname="source-fixture"\nversion="0.0.0"\n'
        'requires-python=">=3.11"\ndependencies=[]\n[build-system]\n'
        'requires=[]\nbuild-backend="stub_backend"\nbackend-path=["."]\n'
    )
    venv.EnvBuilder(with_pip=False).create(root / ".venv")
    for command in (["lock"], ["sync", "--locked"]):
        subprocess.run(
            ["uv", *command, "--offline", "--python", sys.executable],
            cwd=root,
            env=dict(os.environ, UV_PROJECT_ENVIRONMENT=str(root / ".venv")),
            capture_output=True,
            text=True,
            check=True,
        )
    return root / ".venv/bin/python3"


__all__ = ["REPO_ROOT", "SOURCE_PYTHONPATH"]
