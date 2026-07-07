"""``yoke path`` — diagnose and repair PATH for uv / uvx / yoke.

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

PATH_USAGE = "yoke path <check|fix|verify> [--json]"


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
        "ssh_startup_file": diag.ssh_startup_file,
        "ssh_adds_bin": diag.ssh_adds_bin,
        "ssh_managed_block_present": diag.ssh_managed_block_present,
        "ssh_resolved": _resolutions(diag.ssh_resolved),
        "ssh_needs_fix": diag.ssh_needs_fix,
        "needs_fix": diag.needs_fix,
    }


def _render_diagnosis(diag: doctor.PathDiagnosis) -> str:
    future_map = _resolutions(diag.future_resolved)
    future_ok = bool(future_map.get("yoke")) and bool(future_map.get("uv"))
    lines = [
        f"current shell : {diag.current_shell}",
        f"tool bin dir  : {diag.tool_bin_dir}",
        f"on PATH now   : {'yes' if diag.current_on_path else 'no'}",
        f"startup file  : {diag.startup_file}",
        f"future shell  : {'resolves Yoke' if future_ok else 'would NOT find yoke/uv'}",
    ]
    if diag.ssh_startup_file:
        lines.extend([
            f"ssh file      : {diag.ssh_startup_file}",
            "ssh command   : "
            + ("resolves Yoke" if not diag.ssh_needs_fix else "would NOT find yoke/uv"),
        ])
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
    bindir = diag.tool_bin_dir
    block = doctor.render_managed_block(bindir)
    if parsed.print_block:
        print(block)
        return 0

    shell = diag.current_shell
    target = (
        Path(parsed.file)
        if parsed.file
        else Path(diag.startup_file)
    )
    extra_targets = []
    if not parsed.file and diag.ssh_needs_fix and diag.ssh_startup_file:
        ssh_target = Path(diag.ssh_startup_file)
        if ssh_target != target:
            extra_targets.append(ssh_target)
    target_list = [target, *extra_targets]
    print("Yoke will add a managed PATH block to:")
    for item in target_list:
        print(f"  {item}")
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

    changed = any(doctor.apply_fix(item, bindir) for item in target_list)
    resolved = doctor.verify_fresh_login(shell)
    ssh_resolved = doctor.verify_ssh_command(shell)
    verified = all(res.path for res in resolved if res.name in ("uv", "yoke"))
    ssh_verified = all(
        res.path for res in ssh_resolved if res.name in ("uv", "yoke")
    )
    if parsed.json_mode:
        print(
            json.dumps(
                {
                    "applied": changed,
                    "file": str(target),
                    "files": [str(item) for item in target_list],
                    "verified": verified,
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
    if not verified:
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
    resolved = doctor.verify_fresh_login()
    ssh_resolved = doctor.verify_ssh_command()
    if parsed.json_mode:
        print(json.dumps({
            "resolved": _resolutions(resolved),
            "ssh_resolved": _resolutions(ssh_resolved),
        }, indent=2))
    else:
        for res in resolved:
            print(f"  {res.name:6} -> {res.path or 'not found'}")
        if ssh_resolved:
            print("  SSH command probe:")
            for res in ssh_resolved:
                print(f"  {res.name:6} -> {res.path or 'not found'}")
    return 0


def path_group(args: List[str]) -> int:
    print("yoke path — diagnose and repair PATH for uv / uvx / yoke")
    print()
    print("Subcommands:")
    print("  yoke path check [--json]                       diagnose current + future shell PATH")
    print("  yoke path fix [--yes] [--file PATH] [--print-block]  preview, consent, write a managed block, verify")
    print("  yoke path verify [--json]                      check a fresh login shell resolves the tools")
    return 0


__all__ = [
    "PATH_USAGE",
    "path_check",
    "path_fix",
    "path_group",
    "path_verify",
]
