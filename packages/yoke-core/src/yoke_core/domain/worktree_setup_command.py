"""Run a declared lane setup and report its non-blocking outcome."""

from __future__ import annotations

import shlex
import subprocess
import sys

from yoke_contracts.refusal_recovery import compose_refusal


def prepare_setup_command(path: str, project: str | None, timeout: int) -> dict:
    from yoke_core.domain.worktree_deps import get_setup_command

    result = {"status": "skipped", "command": None}
    if not project:
        return result
    try:
        command = get_setup_command(project)
    except Exception as exc:  # noqa: BLE001 — retain the lane and diagnose the read
        result["status"] = "failed"
        print(compose_refusal(
            f"SETUP-COMMAND-UNREADABLE: project {project!r}: {exc}",
            recovery="repair the project connection or capability read, then rerun lane prepare",
        ), file=sys.stderr)
        return result
    result["command"] = command
    if not command:
        return result
    print(f"Installing deps via project setup_command: {command}", file=sys.stderr)
    try:
        completed = subprocess.run(
            command, shell=True, cwd=path, timeout=timeout, stdout=sys.stderr,
        )
        reason = f"exited {completed.returncode}"
        failed = completed.returncode != 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        failed, reason = True, str(exc)
    result["status"] = "failed" if failed else "ran"
    if failed:
        print(compose_refusal(
            f"SETUP-COMMAND-FAILED: command {command!r} {reason} in lane {path!r}",
            recovery=(
                "replace the declaration with yoke projects capability-settings set "
                f"--project {shlex.quote(str(project))} --cap-type setup_command "
                "--settings-json '{\"command\":\"<documented environment command>\"}' "
                "--base '<current setup_command settings JSON>', then rerun lane prepare"
            ),
        ), file=sys.stderr)
    return result
