"""``yoke update`` — safely rerun the official installer for this machine.

Client-local command (no dispatcher function id), registered in
:mod:`yoke_cli.commands.installer_local`. Thin CLI over
:mod:`yoke_cli.config.self_update`; ``--check`` installs nothing and reports
through :mod:`yoke_cli.config.update_check`.
"""

from __future__ import annotations

import argparse
import json
from typing import List

from yoke_cli.config import self_update, update_check

__all__ = ["UPDATE_USAGE", "update"]

UPDATE_USAGE = (
    "yoke update [--channel NAME] [--version VERSION] [--json] | "
    "yoke update --check [--channel NAME] [--json]"
)


def update(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke update")
    parser.add_argument(
        "--channel",
        default=None,
        help="Release channel to update from; default: the configured channel.",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="install this exact release instead of the channel's current one",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "install nothing; prove the installed CLI's exact build (its full "
            "source commit must match the release manifest; the release's "
            "wheel sha256 values are listed), then report the active server's "
            "engine and the channel's latest release, with behind: cli|server|none"
        ),
    )
    parser.add_argument(
        "--json",
        dest="json_mode",
        action="store_true",
        help="Print JSON instead of text.",
    )
    parsed = parser.parse_args(args)
    if parsed.check:
        if parsed.version:
            parser.error("--check compares to the channel's latest; drop --version")
        return _check(parsed.channel, parsed.json_mode)
    try:
        result = self_update.run_update(channel=parsed.channel, version=parsed.version)
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
    if result.get("project_refresh", {}).get("status") == "refreshed":
        print("Refreshed the current checkout’s installed Yoke operating layer.")
    if result["credential_helper_repaired"]:
        print("Rebuilt the git credential helper bundle for this release.")
    for root in result.get("credential_helper_rewritten") or []:
        print(f"Pointed {root} at the current git credential helper.")
    if credential_error:
        print(f"warning: git credential helper repair failed: {credential_error}")
    return 1 if credential_error else 0


def _check(channel: str | None, json_mode: bool) -> int:
    try:
        report = update_check.run_check(channel=channel)
    except self_update.SelfUpdateError as exc:
        if json_mode:
            print(json.dumps({"ok": False, "error": str(exc)}))
        else:
            print(f"yoke update --check: {exc}")
        return 1
    if json_mode:
        print(json.dumps({"ok": True, **report}))
        return 0
    print(f"Channel {report['channel']} latest: v{report['latest_version']}")
    print(
        f"Installed CLI: v{report['cli_version']}, built from "
        f"{report['source_commit']} (matches the release manifest)"
    )
    print("Release wheels (published sha256):")
    for wheel in report["wheels"]:
        print(f"  {wheel['filename']} sha256 {wheel['sha256']}")
    print(
        f"Server engine ({report['destination']}, env {report['env']}): "
        f"v{report['server_engine_version']}"
    )
    print(f"Behind: {report['behind']}")
    if report["next_step"]:
        print(report["next_step"])
    return 0
