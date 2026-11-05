# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import importlib.util

import os

from pathlib import Path

import signal

import subprocess

import sys

import time

import pytest

from yoke_cli.config import cli_release_runtime as runtime


def candidate(root: Path, version: str) -> Path:
    generation = root / "releases" / version
    binary = generation / "tools" / "yoke-cli" / "bin" / "yoke"
    environment = binary.parent.parent
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(environment)],
        check=True,
        capture_output=True,
    )
    site = next((environment / "lib").glob("python*/site-packages"))
    (site / "release_marker.py").write_text(f"VERSION = {version!r}\n")
    package = site / "yoke_cli"
    (package / "config").mkdir(parents=True)
    (package / "__init__.py").touch()
    (package / "config/__init__.py").touch()
    (package / "config/install_binding.py").write_text(
        "def detect(): return {'kind': 'packaged_wheel', 'version': '1.0'}\n"
    )
    (package / "main.py").write_text(
        "import json, sys\n"
        "def main(argv):\n"
        "    if argv == ['long']:\n"
        "        print('ready', flush=True)\n"
        "        sys.stdin.readline()\n"
        "        import release_marker\n"
        "        print(release_marker.VERSION, flush=True)\n"
        "    elif argv == ['hold']:\n"
        "        import os\n"
        "        print(os.getpid(), flush=True)\n"
        "        sys.stdin.readline()\n"
        "    elif argv == ['--version']:\n"
        "        import release_marker\n"
        "        print(release_marker.VERSION)\n"
        "    elif argv[:1] == ['github']:\n"
        "        print(json.dumps({'configured': False}))\n"
    )
    binary.write_text(
        f"#!{environment}/bin/python3\nfrom yoke_cli.main import main\nimport sys\nsys.exit(main(sys.argv[1:]))\n"
    )
    binary.chmod(0o755)
    (generation / "lease").touch()
    (generation / "pending").touch()
    return generation
