#!/usr/bin/env python3
"""Standard-library launcher for the public installer's released CLI.

Ordinary commands use the immutable released CLI launcher.
YOKE_SOURCE_DEV=1 explicitly opts an operator into YOKE_HOME source imports;
claimed-lane checks use ``yoke dev run`` instead. A ``deployment-runs create``
through it is the declared creation bootstrap, so it keeps a ``*-db-admin``
database door its https env would otherwise take over.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_YOKE_HOME = None
RELEASE_RECOVERY = None


def _run_release() -> int:
    uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
    try:
        result = subprocess.run(
            [uv, "tool", "dir"], capture_output=True, text=True, check=True, timeout=5
        )
        tool_root = Path(result.stdout.strip())
        if not tool_root.is_absolute():
            raise ValueError("uv tool dir returned no absolute tool directory")
        launcher = tool_root / "yoke-cli-releases" / "launcher"
        if not launcher.is_file():
            raise FileNotFoundError(f"immutable CLI launcher missing: {launcher}")
        os.execv(str(launcher), [str(launcher), *sys.argv[1:]])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        recovery = (
            RELEASE_RECOVERY
            or "restore the recorded distribution and rerun its installer, then retry"
        )
        print(f"released_cli_unavailable: {exc}; {recovery}", file=sys.stderr)
        return 2
    return 0  # exec replaces this process


def _resolve_yoke_home() -> Path:
    return Path(
        os.environ.get("YOKE_HOME") or DEFAULT_YOKE_HOME or os.path.expanduser("~/yoke")
    )


def _source_paths(home: Path) -> list[Path]:
    package_root = home / "packages"
    paths = []
    if package_root.is_dir():
        paths.extend(sorted(src for src in package_root.glob("*/src") if src.is_dir()))
    paths.append(home)
    return paths


def _prepend_source_paths(home: Path) -> None:
    for path in reversed(_source_paths(home)):
        raw = str(path)
        if raw not in sys.path:
            sys.path.insert(0, raw)


def main() -> int:
    if os.environ.get("YOKE_SOURCE_DEV") != "1":
        return _run_release()
    home = _resolve_yoke_home()
    if not (home / "packages/yoke-cli/src/yoke_cli/__init__.py").is_file():
        print(
            f"source_cli_unavailable: YOKE_HOME names no CLI source at {home}; "
            "set YOKE_HOME to the source checkout or unset YOKE_SOURCE_DEV "
            "to run the released CLI",
            file=sys.stderr,
        )
        return 2
    _prepend_source_paths(home)
    print(f"source authority: explicit operator opt-in at {home}", file=sys.stderr)
    try:
        from yoke_cli.main import main as cli_main
    except ImportError as exc:
        print(
            f"source_cli_unavailable: {exc}; prepare the source environment "
            "and run checks with `yoke dev run -- <command>`",
            file=sys.stderr,
        )
        return 2

    argv = sys.argv[1:]
    if _is_creation_bootstrap(argv):
        from yoke_contracts.direct_database_access import (
            CREATION_BOOTSTRAP_COMMAND,
            direct_database_command,
        )

        with direct_database_command(CREATION_BOOTSTRAP_COMMAND):
            return int(cli_main(argv) or 0)
    return int(cli_main(argv) or 0)


def _is_creation_bootstrap(argv: list[str]) -> bool:
    """Whether *argv* is ``deployment-runs create``, the one bootstrap here."""
    words = [arg for arg in argv if not arg.startswith("-")]
    return any(
        words[index : index + 2] == ["deployment-runs", "create"]
        for index in range(len(words))
    )


if __name__ == "__main__":
    raise SystemExit(main())
