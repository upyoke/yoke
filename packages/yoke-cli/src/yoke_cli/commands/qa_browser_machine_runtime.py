"""``yoke qa browser setup`` before any project exists: the machine runtime only.

The runtime (Node, Playwright, Chromium, its system libraries and sandbox
allowance) belongs to the machine, so first-user setup and every browser
recovery it prints can repair it before a connection or project exists.
A daemon opens one project's signed-in profile, so none starts without a
project, and none is guessed.
"""

from __future__ import annotations

import sys
from pathlib import Path

NO_PROJECT_DETAIL = (
    "browser runtime ready; no project selected, so no browser daemon started. "
    "Pass --project PROJECT, or run inside a project checkout, to start one."
)
NO_PROJECT_PROFILE = {
    "project": None,
    "path": "",
    "status": "no project selected",
}


def prepare(runtime_dir: Path, prerequisite_actions: list[dict[str, str]]) -> dict:
    """Install the machine browser runtime; a failure raises its named recovery."""
    from yoke_harness import browser_setup

    browser_setup.ensure_browser_runtime(emit=lambda line: print(line, file=sys.stderr))
    return {
        "ok": True,
        "dry_run": False,
        "runtime_dir": str(runtime_dir),
        "prerequisite_actions": prerequisite_actions,
        "daemon": {"status": "not_started", "detail": NO_PROJECT_DETAIL},
    }


__all__ = ["NO_PROJECT_DETAIL", "NO_PROJECT_PROFILE", "prepare"]
