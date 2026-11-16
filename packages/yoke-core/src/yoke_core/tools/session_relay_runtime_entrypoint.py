#!/usr/bin/env python3
"""Start one atomically selected relay release on the stable relay Python."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import sysconfig


_RELEASE_HANDLE = None


def _select_release_packages() -> None:
    global _RELEASE_HANDLE
    state_dir = Path(__file__).resolve().parents[2]
    # The stable runtime has no product packages yet. The installer bundles
    # the shared lock owner beside this entrypoint; do not copy its algorithm.
    spec = importlib.util.spec_from_file_location(
        "relay_file_lock", state_dir / "runtime" / "relay_file_lock.py"
    )
    locks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(locks)
    with (state_dir / "__YOKE_RELEASE_LOCK__").open(mode="a+b") as pin_lock:
        locks.acquire_shared(pin_lock.fileno())
        try:
            active = state_dir / "__YOKE_ACTIVE_RELEASE__"
            receipt = json.loads((active / ".yoke-relay-release.json").read_text(encoding="utf-8"))
            release_root = Path(receipt["physical_root"]).resolve(strict=True)
            if release_root.parent != (state_dir / "releases").resolve():
                raise RuntimeError("selected release is outside the owned releases directory")
            _RELEASE_HANDLE = (release_root / ".relay-use.lock").open(mode="a+b")
            locks.acquire_shared(_RELEASE_HANDLE.fileno())
        finally:
            locks.release_exclusive(pin_lock.fileno())
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
    # Name the tree those two variables belong to, in the same breath as
    # setting them. A relay child that starts a foreign CLI drops exactly
    # what this relay owns rather than guessing that root from a release
    # path. The install substitutes the variable's canonical name here.
    os.environ["__YOKE_RELAY_STATE_DIR_ENV__"] = str(state_dir)


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
