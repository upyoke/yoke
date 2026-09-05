#!/usr/bin/env python3
"""Start one atomically selected relay release on the stable relay Python."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import sysconfig


def _select_release_packages() -> None:
    state_dir = Path(__file__).resolve().parents[2]
    release_root = (state_dir / "__YOKE_ACTIVE_RELEASE__").resolve(strict=True)
    runtime_root = Path(sys.prefix).resolve()
    runtime_packages = Path(sysconfig.get_path("purelib")).resolve()
    package_relative = runtime_packages.relative_to(runtime_root)
    release_packages = release_root / package_relative
    if not release_packages.is_dir():
        raise RuntimeError(f"release packages are missing at {release_packages}")

    # Resolve the active pointer once. Every import and child Python then uses
    # that physical release, even if a later install swaps the pointer.
    package_path = str(release_packages)
    sys.path.insert(0, package_path)
    os.environ["PYTHONPATH"] = package_path
    os.environ["VIRTUAL_ENV"] = str(release_root)


def main() -> int:
    try:
        _select_release_packages()
        from yoke_cli.main import main as cli_main

        return int(cli_main(sys.argv[1:]) or 0)
    except Exception as exc:  # noqa: BLE001 - emit an operator-facing refusal
        print(
            "relay_runtime_start_failed: "
            f"{type(exc).__name__}: {exc}. Recovery: retry `yoke relay install` "
            "for this environment.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
