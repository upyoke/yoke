"""Bounded, credential-redacted Docker diagnostics for self-host commands."""

from __future__ import annotations

import subprocess

from yoke_contracts import terminal_detached_process
from yoke_contracts.self_host_bootstrap_output import redact_api_tokens


def _diagnostic(value: str, *, password: bytes = b"") -> str:
    text = str(value or "")
    if password:
        text = text.replace(password.decode("utf-8", errors="replace"), "[REDACTED]")
    text = redact_api_tokens(text).strip()
    printable = "".join(char if char.isprintable() else " " for char in text)
    return printable[-2048:] or "No additional diagnostic was reported."


def import_failure_details(name, password, exec_code, stderr, stdout, completion):
    """Read the one-off container's logs before its caller removes it."""
    try:
        logs = terminal_detached_process.run(
            ("docker", "logs", "--tail", "200", name),
            capture_output=True,
            timeout=30,
            check=False,
        )
        container_log = logs.stdout + logs.stderr
        logs_code = str(logs.returncode)
    except (OSError, subprocess.TimeoutExpired):
        container_log = (
            b"Docker logs unavailable; check Docker access and retry import."
        )
        logs_code = "unavailable"
    try:
        state = terminal_detached_process.run(
            (
                "docker",
                "inspect",
                "--format",
                "{{.State.OOMKilled}} {{.HostConfig.Memory}}",
                name,
            ),
            capture_output=True,
            timeout=30,
            check=False,
        )
        memory_state = state.stdout if state.returncode == 0 else b"unavailable"
    except (OSError, subprocess.TimeoutExpired):
        memory_state = b"unavailable"
    container_code = completion.stdout.strip() if completion else b"unavailable"
    wait_code = str(completion.returncode) if completion else "unavailable"

    def clean(value):
        return _diagnostic(value.decode("utf-8", errors="replace"), password=password)

    return (
        f"docker exec exit: {exec_code}; docker wait exit: {wait_code}; "
        f"container exit: {clean(container_code)}",
        f"Container OOMKilled / memory limit bytes: {clean(memory_state)}",
        f"Exec stderr: {clean(stderr)}",
        f"Exec stdout: {clean(stdout)}",
        f"Container logs (docker logs exit {logs_code}): {clean(container_log)}",
    )
