"""``yoke path`` — diagnose and repair PATH for Yoke and harness CLIs.

Client-local command (no dispatcher function id), registered in
:mod:`yoke_cli.commands.installer_local`. A thin CLI over
:mod:`yoke_cli.config.path_doctor`; the onboarding wizard drives the same
module functions directly for its interactive PATH screens.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
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
        lines.append("fix           : run `yoke path fix`")
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
    parser.add_argument("--file", dest="file", default=None)
    parser.add_argument("--print-block", dest="print_block", action="store_true")
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parser.parse_args(args)

    diag = doctor.diagnose()
    plan = path_repair_plan.build(diag)
    directories = tuple(plan["directories"])
    block = doctor.render_managed_block(directories)
    if parsed.print_block:
        print(block)
        return 0

    shell = diag.current_shell
    target_list = (
        [Path(parsed.file)]
        if parsed.file
        else [Path(path) for path in path_repair_plan.target_paths(plan)]
    )
    print("Yoke keeps login and non-login/SSH PATH outcomes separate:")
    for line in path_repair_plan.description_lines(plan):
        print(f"  {line}")
    if not target_list:
        print("  Both startup surfaces already contain the current managed block.")
    print()
    print(block + "\n")
    if not parsed.yes:
        try:
            answer = input("Apply this change? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("No changes made.")
            return 0

    changes = [doctor.apply_fix(item, directories) for item in target_list]
    changed = any(changes)
    resolved = doctor.verify_fresh_login(shell, managed_path_dirs=directories)
    ssh_resolved = doctor.verify_ssh_command(shell, managed_path_dirs=directories)
    login_verified = path_repair_plan.verification_ok(resolved, plan)
    ssh_verified = path_repair_plan.verification_ok(ssh_resolved, plan)
    if parsed.json_mode:
        print(
            json.dumps(
                {
                    "applied": changed,
                    "files": [str(item) for item in target_list],
                    "directories": list(directories),
                    "login_verified": login_verified,
                    "ssh_verified": ssh_verified,
                    "resolved": _resolutions(resolved),
                    "ssh_resolved": _resolutions(ssh_resolved),
                },
                indent=2,
            )
        )
        return 0
    print(("Applied." if changed else "Already up to date."))
    for item in target_list:
        print(f"  {item}")
    for res in resolved:
        print(f"  {res.name:6} -> {res.path or 'not found'}")
    if ssh_resolved:
        print("  SSH command probe:")
        for res in ssh_resolved:
            print(f"  {res.name:6} -> {res.path or 'not found'}")
    if not login_verified:
        print(
            "Note: a fresh login shell could not resolve yoke/uv yet; "
            "open a new terminal to confirm."
        )
    if not ssh_verified:
        print(
            "Note: an SSH one-shot command could not resolve yoke/uv yet; "
            "try `ssh host 'yoke status'` to confirm."
        )
    return 0


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
    return 0


def path_group(args: List[str]) -> int:
    print("yoke path — repair login and SSH PATH for Yoke and harness CLIs")
    print()
    print("Subcommands:")
    print(
        "  yoke path check [--json]                       diagnose current + future shell PATH"
    )
    print(
        "  yoke path fix [--yes] [--file PATH] [--print-block]  preview, consent, write a managed block, verify"
    )
    print(
        "  yoke path verify [--json]                      check a fresh login shell resolves the tools"
    )
    return 0


__all__ = [
    "path_check",
    "path_fix",
    "path_group",
    "path_verify",
]
