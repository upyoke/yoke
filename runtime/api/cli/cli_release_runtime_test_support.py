"""Shared setup for release runtime tests: real candidate environments."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shlex
import subprocess
import sys

from yoke_cli.config import cli_release_runtime as runtime

MAIN = """import json, sys
def main(argv):
    if argv == ['long']:
        print('ready', flush=True)
        sys.stdin.readline()
        import release_marker
        print(release_marker.VERSION, flush=True)
    elif argv == ['hold']:
        import os
        print(os.getpid(), flush=True)
        sys.stdin.readline()
    elif argv == ['--version']:
        import release_marker
        print(release_marker.VERSION)
    elif argv[:1] == ['github']:
        print(json.dumps({'configured': False}))
"""


def candidate(root: Path, version: str) -> Path:
    """A pending release whose fake ``yoke_cli`` reports ``version``."""
    generation = root / "releases" / version
    environment = generation / "tools" / "yoke-cli"
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(environment)],
        check=True,
        capture_output=True,
    )
    site = next(
        path
        for pattern in ("lib/python*/site-packages", "Lib/site-packages")
        for path in environment.glob(pattern)
    )
    (site / "release_marker.py").write_text(f"VERSION = {version!r}\n")
    package = site / "yoke_cli"
    (package / "config").mkdir(parents=True)
    (package / "__init__.py").touch()
    (package / "config/__init__.py").touch()
    (package / "config/install_binding.py").write_text(
        "def detect(): return {'kind': 'packaged_wheel', 'version': '1.0'}\n"
    )
    (package / "main.py").write_text(MAIN)
    (generation / "lease").touch()
    (generation / "pending").touch()
    return generation


def yoke(bin_dir: Path) -> str:
    """The public command a shell on this OS runs."""
    return str(bin_dir / ("yoke.cmd" if runtime.WINDOWS else "yoke"))


def version(bin_dir: Path) -> str:
    return subprocess.check_output([yoke(bin_dir), "--version"], text=True).strip()


@contextmanager
def running(generation: Path):
    """Hold a release the way a running command does on this OS."""
    with (generation / "lease").open("r") as lease:
        if not runtime.WINDOWS:
            import fcntl

            fcntl.flock(lease, fcntl.LOCK_SH)
        yield lease


def point_current(root: Path, generation: Path) -> None:
    """Publish ``generation`` without probing it, with a POSIX ``python`` shim
    that follows ``current`` as the launcher's ``--python`` mode does."""
    root.mkdir(parents=True, exist_ok=True)
    runtime._replace(root / "current", generation.name + "\n")
    shim = root / "python"
    if not shim.exists():
        release = '"$r/releases/$(cat "$r/current")/tools/yoke-cli/bin/python3"'
        shim.write_text(f'#!/bin/sh\nr={shlex.quote(str(root))}\nexec {release} "$@"\n')
        shim.chmod(0o755)
