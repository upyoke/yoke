"""Name a failed desktop process stop by the cause the stop actually proved.

Only the stop script's own survivor list proves a process is still running. A
desktop task that timed out or left cleanup unresolved keeps that cause and its
bounded task facts; anything else is a generic stop failure. Every outcome
refuses the reset. Process inputs, raw command output and exception text stay
out of the receipt.
"""

import re

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.test_machine_types import HostActionResult
from yoke_harness.native_windows.desktop_job import RECOVERY, TIMEOUT, UNRESOLVED

PROCESS_RUNNING = "windows_reset_profile_process_running"
STOP_FAILED = "windows_reset_profile_process_stop_failed"
_TASK = re.compile(r"YokeQa-[0-9a-f]{32}")
_KNOWN = {
    "phase": ("upload", "task_start", "receipt"),
    "cleanup": ("pending", "verified_absent", "unverified", "preserved_ambiguous_upload"),
    "process_cleanup": (
        "verified_empty", "missing desktop job receipt",
        "owned processes remained active after termination",
    ),
}


def desktop_task_record(result):
    """Keep only the desktop task's identity, phase and cleanup outcome."""
    diagnostics = getattr(result, "desktop_diagnostics", None)
    record = {"exit_code": result.returncode}
    if not isinstance(diagnostics, dict):
        return record
    if isinstance(diagnostics.get("task"), str) and _TASK.fullmatch(diagnostics["task"]):
        record["task"] = diagnostics["task"]
    for key, allowed in _KNOWN.items():
        if diagnostics.get(key) in allowed:
            record[key] = diagnostics[key]
    if "task_cleanup_error" in diagnostics:
        record["task_files_cleanup"] = "failed"
    return record


def stop_failure(result):
    """Refuse a reset whose desktop process stop returned nonzero."""
    stderr = result.stderr or ""
    task = desktop_task_record(result)
    marker = stderr.find(PROCESS_RUNNING + ":")
    if marker >= 0 and result.returncode != 124:
        # The stop script's positive refusal: it names each observed survivor.
        survivors = stderr[marker:].splitlines()[0].strip()
        return HostActionResult(False, {"recovery": survivors, "desktop_task": task}, PROCESS_RUNNING)
    if result.returncode == 124 and stderr.startswith(TIMEOUT + ":"):
        cause = TIMEOUT
    elif UNRESOLVED + ":" in stderr:
        cause = UNRESOLVED
    else:
        return HostActionResult(
            False,
            {
                "recovery": compose_refusal(
                    f"{STOP_FAILED}: the desktop process stop exited {result.returncode} "
                    "without a survivor list or a desktop task cause",
                    recovery="inspect the signed-in standard-user desktop, then rerun yoke test-machine reset",
                ),
                "desktop_task": task,
            },
            STOP_FAILED,
        )
    task["cleanup_unresolved"] = UNRESOLVED + ":" in stderr
    facts = ", ".join(f"{key} {task[key]}" for key in ("task", "phase", "process_cleanup") if key in task)
    return HostActionResult(
        False,
        {
            "recovery": compose_refusal(
                f"{cause}: the desktop process stop did not finish ({facts or 'no task facts'}); "
                "it observed no surviving test-user process",
                recovery=f"{RECOVERY}, then rerun yoke test-machine reset",
            ),
            "desktop_task": task,
        },
        cause,
    )
