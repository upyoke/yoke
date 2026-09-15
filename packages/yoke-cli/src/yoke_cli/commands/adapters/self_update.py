"""``yoke update`` — safely rerun the official installer for this machine.

Client-local command (no dispatcher function id), registered in
:mod:`yoke_cli.commands.installer_local`. Thin CLI over
:mod:`yoke_cli.config.self_update`.
"""

from __future__ import annotations

import argparse
import json
from typing import List

from yoke_cli.config import self_update

__all__ = ["UPDATE_USAGE", "update"]

UPDATE_USAGE = "yoke update [--channel NAME] [--json]"


def update(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke update")
    parser.add_argument("--channel", default=None)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parser.parse_args(args)
    try:
        result = self_update.run_update(channel=parsed.channel)
    except self_update.SelfUpdateError as exc:
        if parsed.json_mode:
            print(json.dumps({"ok": False, "error": str(exc)}))
        else:
            print(f"yoke update: {exc}")
        return 1
    credential_error = result["credential_helper_error"]
    if parsed.json_mode:
        print(json.dumps({"ok": credential_error is None, **result}))
        return 1 if credential_error else 0
    if result["already_current"]:
        print(
            f"Yoke is already current at v{result['new_version']} "
            f"({result['channel']})."
        )
    else:
        print(
            f"Updated Yoke {result['old_version']} -> {result['new_version']} "
            f"({result['channel']})."
        )
    if result["credential_helper_repaired"]:
        print("Rebuilt the git credential helper bundle a reinstall had wiped.")
    if credential_error:
        print(f"warning: git credential helper repair failed: {credential_error}")
    return 1 if credential_error else 0
