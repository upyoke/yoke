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
        "needs_fix": diag.needs_fix,
    }


def _render_diagnosis(diag: doctor.PathDiagnosis) -> str:
    plan = path_repair_plan.build(diag)
    future_ok = path_repair_plan.verification_ok(diag.future_resolved, plan)
    ssh_ok = path_repair_plan.verification_ok(diag.ssh_resolved, plan)
    lines = [
        f"current shell : {diag.current_shell}",
        f"tool bin dir  : {diag.tool_bin_dir}",
        f"on PATH now   : {'yes' if diag.current_on_path else 'no'}",
        f"login file    : {diag.startup_file}",
        "login shell   : "
        + ("resolves required tools" if future_ok else "needs PATH repair"),
    ]
    if diag.ssh_startup_file:
        lines.extend(
            [
                f"ssh file      : {diag.ssh_startup_file}",
                "ssh command   : "
                + ("resolves required tools" if ssh_ok else "needs PATH repair"),
                "ssh reason    : non-login shells never read the login startup file",
            ]
        )
    lines.append("managed dirs  : " + ", ".join(diag.managed_path_dirs))
    for resolution in diag.harness_clis:
        lines.append(
            f"{resolution.executable:14}: "
            + (resolution.path or "not installed; repair remains re-runnable")
        )
    for label, winner in (
        ("current yoke", diag.yoke_shadowed_by),
        ("future yoke", diag.future_yoke_shadowed_by),
        ("ssh yoke", diag.ssh_yoke_shadowed_by),
    ):
        if winner:
            lines.append(
                f"{label:14}: {diag.preferred_yoke_path} exists, but {winner} wins"
            )
    if diag.needs_fix:
        lines.append(
            "fix           : run `uv tool update-shell`, then open a new terminal"
        )
    return "\n".join(lines)


def path_check(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke path check")
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parser.parse_args(args)
    diag = doctor.diagnose()
    if parsed.json_mode:
        print(json.dumps(_diagnosis_json(diag), indent=2))
    else:
        print(_render_diagnosis(diag))
    return 0


def path_fix(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke path fix")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parser.parse_args(args)
    if not parsed.yes:
        print("Run uv tool update-shell; uv selects the shell configuration to update.")
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
        print(str(exc))
        return 1
    resolved = doctor.verify_fresh_login()
    verified = path_repair_plan.verification_ok(resolved, {})
    if parsed.json_mode:
        print(
            json.dumps(
                {
                    "command": path_repair_plan.UPDATE_SHELL_COMMAND,
                    "output": output,
                    "login_verified": verified,
                    "resolved": _resolutions(resolved),
                }
            )
        )
    else:
        print(output.strip())
        print("Open a new terminal to use the updated PATH.")
    if not verified:
        print(
            "fresh_login_path_unresolved: run `uv tool update-shell`, "
            "check shell configuration that overrides PATH, then open a new terminal."
        )
    return 0 if verified else 1


def path_verify(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke path verify")
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parser.parse_args(args)
    diag = doctor.diagnose()
    resolved = doctor.verify_fresh_login(
        diag.current_shell, managed_path_dirs=diag.managed_path_dirs
    )
    ssh_resolved = doctor.verify_ssh_command(
        diag.current_shell, managed_path_dirs=diag.managed_path_dirs
    )
    if parsed.json_mode:
        print(
            json.dumps(
                {
                    "resolved": _resolutions(resolved),
                    "ssh_resolved": _resolutions(ssh_resolved),
                },
                indent=2,
            )
        )
    else:
        for res in resolved:
            print(f"  {res.name:6} -> {res.path or 'not found'}")
        if ssh_resolved:
            print("  SSH command probe:")
            for res in ssh_resolved:
                print(f"  {res.name:6} -> {res.path or 'not found'}")
    if not any(row.name == "yoke" and row.path for row in resolved):
        print(
            "fresh_login_path_unresolved: run `uv tool update-shell`, then open a new terminal."
        )
        return 1
    return 0


def path_group(args: List[str]) -> int:
    print("yoke path — diagnose shell PATH and delegate setup to uv")
    print()
    print("Subcommands:")
    print(
        "  yoke path check [--json]                       diagnose current + future shell PATH"
    )
    print(
        "  yoke path fix [--yes] [--json]                   run uv tool update-shell and verify"
    )
    print(
        "  yoke path verify [--json]                      probe the actual fresh login shell PATH"
    )
    return 0


__all__ = [
    "path_check",
    "path_fix",
    "path_group",
    "path_verify",
]
