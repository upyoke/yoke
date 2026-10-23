"""``yoke path`` — diagnose and repair PATH for Yoke and harness CLIs.

Client-local command (no dispatcher function id), registered in
:mod:`yoke_cli.commands.installer_local`. A thin CLI over
:mod:`yoke_cli.config.path_doctor`; the onboarding wizard drives the same
module functions directly for its interactive PATH screens.
"""

from __future__ import annotations

import argparse
import json
from typing import List

from yoke_cli.config import path_doctor as doctor
from yoke_cli.config import path_repair_plan


def _resolutions(resolved: list[doctor.ToolResolution]) -> dict[str, str | None]:
    return {res.name: res.path for res in resolved}


def _diagnosis_json(diag: doctor.PathDiagnosis) -> dict:
    return {
        "current_shell": diag.current_shell,
        "tool_bin_dir": diag.tool_bin_dir,
        "current_on_path": diag.current_on_path,
        "current_resolved": _resolutions(diag.current_resolved),
        "startup_file": diag.startup_file,
        "future_adds_bin": diag.future_adds_bin,
        "managed_block_present": diag.managed_block_present,
        "future_resolved": _resolutions(diag.future_resolved),
        "login_needs_fix": diag.login_needs_fix,
        "ssh_startup_file": diag.ssh_startup_file,
        "ssh_adds_bin": diag.ssh_adds_bin,
        "ssh_managed_block_present": diag.ssh_managed_block_present,
        "ssh_resolved": _resolutions(diag.ssh_resolved),
        "ssh_needs_fix": diag.ssh_needs_fix,
        "preferred_yoke_path": diag.preferred_yoke_path,
        "yoke_shadowed_by": diag.yoke_shadowed_by,
        "future_yoke_shadowed_by": diag.future_yoke_shadowed_by,
        "ssh_yoke_shadowed_by": diag.ssh_yoke_shadowed_by,
        "managed_path_dirs": list(diag.managed_path_dirs),
        "harness_clis": [row.to_json() for row in diag.harness_clis],
        "contexts": list(diag.contexts),
        "needs_fix": diag.needs_fix,
    }


def _render_diagnosis(diag: doctor.PathDiagnosis) -> str:
    lines = [
        f"current shell : {diag.current_shell}",
        f"tool bin dir  : {diag.tool_bin_dir}",
        f"on PATH now   : {'yes' if diag.current_on_path else 'no'}",
        f"login file    : {diag.startup_file}",
        "login shell   : "
        + ("needs PATH repair" if diag.login_needs_fix else "resolves canonical Yoke"),
    ]
    if diag.ssh_startup_file:
        lines.extend(
            [
                f"ssh file      : {diag.ssh_startup_file}",
                "ssh command   : "
                + ("needs PATH repair" if diag.ssh_needs_fix else "resolves canonical Yoke"),
                "ssh reason    : non-login shells never read the login startup file",
            ]
        )
    for row in diag.contexts:
        winner = row["resolved"].get("yoke") or "not found"
        status = row["reason"] if row["needs_fix"] else "ok"
        lines.append(
            f"{row['shell']} {row['context']}: {status}; "
            f"yoke -> {winner}; expected {diag.preferred_yoke_path}"
        )
        if row["needs_fix"]:
            lines.append(f"  recovery: {row['recovery']}")
    lines.append("managed dirs  : " + ", ".join(diag.managed_path_dirs))
    for resolution in diag.harness_clis:
        lines.append(
            f"{resolution.executable:14}: "
            + (resolution.path or "not installed; repair remains re-runnable")
        )
    for label, resolved in (
        ("current yoke", diag.current_resolved),
        ("future yoke", diag.future_resolved),
        ("ssh yoke", diag.ssh_resolved),
    ):
        winner = _resolutions(resolved).get("yoke") or "not found"
        lines.append(
            f"{label:14}: {winner}; expected {diag.preferred_yoke_path}"
        )
    if diag.yoke_shadowed_by:
        lines.append(
            "shell_path_shadowed: the current terminal still selects "
            f"{diag.yoke_shadowed_by}. Put {diag.tool_bin_dir} first on PATH "
            "or open a new terminal after correcting startup configuration; "
            "run `yoke path verify` again."
        )
    return "\n".join(lines)


def path_check(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke path check",
        description="Show actual and canonical Yoke paths for every supported shell context.",
    )
    parser.add_argument(
        "--json", dest="json_mode", action="store_true", help="Print JSON output."
    )
    parsed = parser.parse_args(args)
    diag = doctor.diagnose()
    if parsed.json_mode:
        print(json.dumps(_diagnosis_json(diag), indent=2))
    else:
        print(_render_diagnosis(diag))
        if diag.needs_fix:
            print("Repair owned blocks with `yoke path fix --yes`; remaining user-owned "
                  "PATH overrides require the context recovery above.")
    return 1 if diag.needs_fix else 0


def path_fix(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke path fix",
        description="Repair only Yoke-owned blocks; remaining overrides need manual correction.",
    )
    parser.add_argument("--yes", action="store_true", help="Apply without asking first.")
    parser.add_argument(
        "--json", dest="json_mode", action="store_true", help="Print JSON output."
    )
    parsed = parser.parse_args(args)
    if not parsed.yes:
        print("Repair Yoke-owned PATH blocks in supported shell startup files.")
        try:
            answer = input("Apply this change? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("No changes made.")
            return 0
    try:
        output = doctor.update_shell()
    except OSError as exc:
        print(
            json.dumps({"verified": False, "error": str(exc)})
            if parsed.json_mode
            else str(exc)
        )
        return 1
    diag = doctor.diagnose()
    verified = not diag.needs_fix
    if parsed.json_mode:
        print(
            json.dumps(
                {
                    "command": path_repair_plan.UPDATE_SHELL_COMMAND,
                    "output": output,
                    "login_verified": not diag.login_needs_fix,
                    "verified": verified,
                    "contexts": list(diag.contexts),
                    "resolved": _resolutions(diag.future_resolved),
                }
            )
        )
    else:
        print("Yoke-owned PATH block repair:")
        print(output.strip())
        print(_render_diagnosis(diag))
        if verified:
            print("PATH verified. Open a new terminal to use the updated PATH.")
    if not verified and not parsed.json_mode:
        print(
            "shell_path_unresolved: PATH verification failed; follow the context "
            "recovery above. Repeating unchanged owned-block repair cannot fix "
            "user-owned PATH overrides."
        )
    return 0 if verified else 1


def path_verify(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke path verify",
        description="Fail if any required shell context cannot resolve canonical Yoke.",
    )
    parser.add_argument(
        "--json", dest="json_mode", action="store_true", help="Print JSON output."
    )
    parsed = parser.parse_args(args)
    diag = doctor.diagnose()
    if parsed.json_mode:
        print(
            json.dumps(
                {
                    "resolved": _resolutions(diag.future_resolved),
                    "ssh_resolved": _resolutions(diag.ssh_resolved),
                    "contexts": list(diag.contexts),
                    "verified": not diag.needs_fix,
                },
                indent=2,
            )
        )
    else:
        print(_render_diagnosis(diag))
    return 1 if diag.needs_fix else 0


def path_group(args: List[str]) -> int:
    print("yoke path — diagnose shell PATH and repair Yoke-owned startup entries")
    print()
    print("Subcommands:")
    print(
        "  yoke path check [--json]                       check every supported shell context"
    )
    print(
        "  yoke path fix [--yes] [--json]                   repair owned startup entries and verify"
    )
    print(
        "  yoke path verify [--json]                      probe login, interactive, non-login and SSH PATH"
    )
    return 0


__all__ = [
    "path_check",
    "path_fix",
    "path_group",
    "path_verify",
]
