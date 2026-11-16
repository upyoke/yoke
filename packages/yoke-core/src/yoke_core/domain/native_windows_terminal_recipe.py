"""Native PowerShell recipes with the shared staging and assertion contract."""

import time

from yoke_contracts.machine_qa_result_safety import redact_machine_qa_value
from yoke_contracts.runtime_ports.ssh_windows_host_operations import (
    get_ssh_windows_host_operations,
)
from yoke_contracts.test_machine_types import HostActionResult
from yoke_core.domain.machine_qa_setup_exit import marker_exit_code
from yoke_core.domain.ssh_mac_terminal_recipe_support import (
    stage_recipe_files,
    run_command_recipe,
    recipe_assertion_failures,
)


def execute_recipe(
    control,
    *,
    entry_surface,
    required_completion,
    config,
    progress_callback=None,
    allowed_operator_urls=(),
):
    staged, extra_secrets = stage_recipe_files(control, config)
    secrets = (*control.secret_values, *extra_secrets)
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
            terminal = get_ssh_windows_host_operations().WindowsTerminal(control)
            result = _interactive(
                terminal,
                entry_surface,
                required_completion,
                config,
                progress_callback,
                secrets,
                control._pending_terminal_size,
            )
        return HostActionResult(
            result.ok,
            redact_machine_qa_value(
                {
                    **result.evidence,
                    "staged_files": staged,
                    "connection": control.check_connection().evidence,
                },
                secrets,
            ),
            result.error_code,
        )
    finally:
        paths = [row["remote_path"] for row in staged]
        if paths:
            removed = control.run_command(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-Command",
                    "foreach($p in $args){Remove-Item -LiteralPath $p -Force -ErrorAction Stop}",
                    *paths,
                ]
            )
            if removed.returncode:
                raise RuntimeError(
                    "windows_recipe_cleanup_failed: remove the case staged files before releasing its lease"
                )


def _interactive(terminal, entry, required, config, progress, secrets, size):
    deadline = time.monotonic() + float(config["max_wall_seconds"])
    rows = []
    try:
        if not terminal.open(entry, size):
            raise RuntimeError(
                "windows_terminal_unavailable: unlock the test desktop and verify its native console"
            )
        for action in config["actions"]:
            if action.get("operator_gate"):
                raise RuntimeError(
                    "windows_operator_gate_requires_human: finish sign-ins on the native desktop before capturing the golden and rerun this case"
                )
            text = terminal.wait_for(action.get("ready_text", []), deadline, progress)
            if text is None:
                raise RuntimeError(
                    "windows_terminal_readiness_timeout: inspect the native console and correct its expected readiness text"
                )
            for key in action["keys"]:
                if key.startswith("paste_file:"):
                    key = (
                        terminal.control.read_text(key.removeprefix("paste_file:"))
                        or ""
                    )
                if not terminal.send(key, submit=False):
                    raise RuntimeError(
                        "windows_terminal_input_failed: unlock and focus the native console before retrying"
                    )
            wait = float(action.get("wait_seconds", config["step_delay"]))
            if time.monotonic() + wait > deadline:
                raise RuntimeError(
                    "windows_recipe_timeout: shorten action delays or raise the case wall-time bound"
                )
            time.sleep(wait)
            text = terminal.wait_for(
                action.get("completion_text", []), deadline, progress
            )
            if text is None:
                raise RuntimeError(
                    "windows_terminal_completion_timeout: inspect the unmet completion expectation and rerun"
                )
            row = {
                "key": str(action["step"]),
                "reached": bool(text.strip()),
                "transcript": text,
            }
            if row["key"] in config["capture_checkpoints"]:
                row.update(terminal.capture_window())
            rows.append(row)
        combined = "\n".join(row["transcript"] for row in rows)
        failures = recipe_assertion_failures(
            combined,
            expected_text=config["expected_text"],
            post_checks=config["post_checks"],
            secret_values=secrets,
            terminal_exit_code=marker_exit_code(terminal.transcript()),
        )
        completed = any(row["key"] == required and row["reached"] for row in rows)
        ok = completed and not failures
        return HostActionResult(
            ok,
            {
                "steps": rows,
                "transcript": combined,
                "assertion_failures": failures,
                "terminal_backend": "windows-console",
            },
            None if ok else "terminal_completion_not_proved",
        )
    finally:
        if not terminal.close():
            raise RuntimeError(
                "windows_terminal_cleanup_failed: stop the test console process tree before releasing its lease"
            )
