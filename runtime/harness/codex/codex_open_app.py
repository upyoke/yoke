"""Launch Codex Desktop with Yoke's hook pack available.

Python owner for the former ``runtime/harness/codex/open-app.sh`` wrapper.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _resolve_codex_bin() -> str | None:
    cli = shutil.which("codex")
    if cli:
        return cli
    app_bin = Path("/Applications/Codex.app/Contents/Resources/codex")
    if app_bin.is_file() and os.access(app_bin, os.X_OK):
        return str(app_bin)
    return None


def _resolve_root() -> str | None:
    yoke_root = os.environ.get("YOKE_ROOT", "")
    if yoke_root:
        return yoke_root
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m runtime.harness.codex.codex_open_app",
        description="Launch Codex Desktop for Yoke",
    )
    parser.add_argument("codex_args", nargs="*", help="Additional codex app flags")
    args = parser.parse_args(argv)

    codex_bin = _resolve_codex_bin()
    if not codex_bin:
        print(
            "codex_open_app: could not find Codex CLI binary in PATH or /Applications/Codex.app",
            file=sys.stderr,
        )
        return 1

    root = _resolve_root()
    if not root:
        print("codex_open_app: could not resolve git root", file=sys.stderr)
        return 1

    os.execvp(codex_bin, [codex_bin, "app", *args.codex_args, root])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
