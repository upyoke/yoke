"""Bounded Linux tmux recipes using the shared staging and assertion protocol."""

from __future__ import annotations

import time
from typing import Any
from yoke_core.domain.machine_qa_result_safety import redact_machine_qa_value
from yoke_core.domain.ssh_mac_terminal_recipe_support import (
    recipe_assertion_failures,
    run_command_recipe,
    send_recipe_keys,
    stage_recipe_files,
)
from yoke_core.domain.ssh_mac_terminal_recipe_cleanup import with_staged_cleanup
from yoke_harness.ssh_linux_terminal import (
    LinuxTerminal,
    SCREENSHOT_DEFERRAL,
    SCREENSHOT_RECOVERY,
)
from yoke_harness.test_machine_types import HostActionResult


def _wait(terminal: LinuxTerminal, expected, deadline, progress_callback):
    while time.monotonic() < deadline:
        text = terminal.transcript()
        if all(value in text for value in expected):
            return text
        if progress_callback:
            progress_callback()
        time.sleep(0.2)
    return None


def _interactive(
    control,
    *,
    entry_surface,
    required_completion,
    config,
    secrets,
    size,
    progress_callback,
):
    terminal = LinuxTerminal(control)
    deadline = time.monotonic() + float(config["max_wall_seconds"])
    rows = []
    result = HostActionResult(False, {}, "linux_terminal_recipe_failed")
    try:
        if not terminal.open(entry_surface, size):
            return HostActionResult(
                False,
                {"recovery": "Install tmux and repair the non-root user's SSH shell."},
                "linux_tmux_unavailable",
            )
        initial_wait = float(config["start_delay"])
        if initial_wait > max(0, deadline - time.monotonic()):
            return HostActionResult(
                False,
                {"recovery": "Keep start_delay inside max_wall_seconds."},
                "terminal_recipe_timed_out",
            )
        time.sleep(initial_wait)
        for action in config["actions"]:
            if action.get("operator_gate"):
                return HostActionResult(
                    False,
                    {
                        "steps": rows,
                        "designed_deferrals": [
                            {
                                "code": "headless_linux_browser_approval_unavailable",
                                "outcome": "deferred",
                            }
                        ],
                        "recovery": "Use headless device-auth sign-in before golden capture; use a macOS Test Machine for browser approval recipes.",
                    },
                    "headless_linux_browser_approval_unavailable",
                )
            if time.monotonic() >= deadline:
                return HostActionResult(
                    False,
                    {
                        "steps": rows,
                        "recovery": "Repair the stalled application or increase the declared bounded recipe budget.",
                    },
                    "terminal_recipe_timed_out",
                )
            ready = _wait(
                terminal,
                action.get("ready_text", ()),
                min(
                    deadline,
                    time.monotonic() + float(action.get("ready_timeout_seconds", 30)),
                ),
                progress_callback,
            )
            if ready is None:
                return HostActionResult(
                    False,
                    {
                        "steps": rows,
                        "waiting_for": action.get("ready_text", ()),
                        "recovery": "Inspect the readiness text and repair the application before retrying.",
                    },
                    "terminal_action_not_ready",
                )
            if not send_recipe_keys(
                control._run,
                backend="tmux",
                session=terminal.session,
                keys=action["keys"],
            ):
                return HostActionResult(
                    False,
                    {
                        "steps": rows,
                        "recovery": "Repair the tmux input bridge and rerun.",
                    },
                    "terminal_input_failed",
                )
            delay = float(action.get("wait_seconds", config["step_delay"]))
            if delay > max(0, deadline - time.monotonic()):
                return HostActionResult(
                    False,
                    {
                        "steps": rows,
                        "recovery": "Keep action delays inside max_wall_seconds.",
                    },
                    "terminal_recipe_timed_out",
                )
            time.sleep(delay)
            transcript = _wait(
                terminal, action.get("completion_text", ()), deadline, progress_callback
            )
            if transcript is None:
                return HostActionResult(
                    False,
                    {
                        "steps": rows,
                        "recovery": "Repair the declared completion expectation and rerun.",
                    },
                    "terminal_completion_not_proved",
                )
            rows.append(
                {
                    "key": str(action["step"]),
                    "reached": bool(transcript.strip()),
                    "transcript": transcript,
                }
            )
        combined = "\n".join(row["transcript"] for row in rows)
        import re

        exits = re.findall(
            r"^__YOKE_EXIT_([0-9]+)\s*$", terminal.transcript(), re.MULTILINE
        )
        exit_code = int(exits[-1]) if exits else None
        failures = recipe_assertion_failures(
            combined,
            expected_text=config["expected_text"],
            post_checks=config["post_checks"],
            secret_values=secrets,
            terminal_exit_code=exit_code,
        )
        if exit_code is not None and exit_code not in set(
            config["expected_return_codes"]
        ):
            failures.append(f"return code {exit_code} not in expected set")
        if not any(
            row["key"] == required_completion and row["reached"] for row in rows
        ):
            failures.append("required completion was not reached")
        result = HostActionResult(
            not failures,
            {
                "execution_mode": "terminal-multiplexer",
                "terminal_backend": "tmux",
                "steps": rows,
                "required_completion": required_completion,
                "exit_code": exit_code,
                "assertion_failures": failures,
                "capture_degraded_reason": SCREENSHOT_DEFERRAL,
                "designed_deferrals": [
                    {
                        "code": SCREENSHOT_DEFERRAL,
                        "outcome": "deferred",
                        "recovery": SCREENSHOT_RECOVERY,
                    }
                ],
                "recovery": "Repair the named recipe assertions and rerun."
                if failures
                else None,
            },
            "terminal_recipe_assertion_failed" if failures else None,
        )
        return result
    finally:
        if not terminal.close():
            return HostActionResult(
                False,
                {
                    "session": terminal.session,
                    "recovery": "Restore SSH reachability and terminate the named yoke-qa tmux session before retrying.",
                },
                "linux_tmux_cleanup_failed",
            )


def execute_linux_recipe(
    control: Any,
    *,
    entry_surface,
    required_completion,
    config,
    size,
    progress_callback=None,
):
    ok, staged, staged_secrets = stage_recipe_files(
        config["stage_files"], upload_bytes=control._upload_bytes
    )
    if not ok:
        return with_staged_cleanup(
            control._run,
            HostActionResult(
                False,
                {
                    "staged_files": staged,
                    "recovery": "Repair the declared source and remote owner-only path.",
                },
                "terminal_stage_file_failed",
            ),
            staged,
        )
    secrets = control.secret_values + staged_secrets
    try:
        if config["execution_mode"] == "ssh-command":
            result = run_command_recipe(
                control._run,
                entry_surface=entry_surface,
                config=config,
                staged=staged,
                secret_values=secrets,
            )
        else:
            result = _interactive(
                control,
                entry_surface=entry_surface,
                required_completion=required_completion,
                config=config,
                secrets=secrets,
                size=size,
                progress_callback=progress_callback,
            )
        safe = HostActionResult(
            result.ok,
            redact_machine_qa_value(
                {**result.evidence, "staged_files": staged}, secrets
            ),
            result.error_code,
        )
        return with_staged_cleanup(control._run, safe, staged)
    except Exception:
        with_staged_cleanup(
            control._run,
            HostActionResult(False, {}, "linux_terminal_recipe_failed"),
            staged,
        )
        raise
