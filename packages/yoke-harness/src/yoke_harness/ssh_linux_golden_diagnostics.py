"""Retained transport evidence for Linux home archive operations."""

from datetime import datetime, timezone
from pathlib import Path
import re
import shlex
import tempfile

from yoke_contracts.machine_qa_failures import bounded_machine_qa_diagnostic
from yoke_harness.test_machine_types import HostActionResult
from yoke_harness.ssh_test_machine_transport import SshTestMachineTransport


def _sanitize(text, secrets):
    for secret in sorted({value for value in secrets if value}, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(
        r"-----BEGIN [^-\n]*PRIVATE KEY-----.*?-----END [^-\n]*PRIVATE KEY-----",
        "[REDACTED]",
        text,
        flags=re.DOTALL,
    )
    # OpenSSH prints the entire submitted program at debug level. Retain the
    # transport exchange, not executable payloads or their embedded data.
    lines = []
    payload = False
    for line in text.splitlines():
        if "Sending command:" in line:
            payload = True
            lines.append("debug1: Sending command: [REDACTED]")
        elif not payload or re.match(r"debug[123]: ", line):
            payload = False
            lines.append(line)
    return "\n".join(lines) + "\n"


def run_golden_command(control, command, *, input_text, timeout):
    """Run once through the existing SSH transport; journal failure is evidence."""
    if not isinstance(control, SshTestMachineTransport):
        return control._run(command, input_text=input_text, timeout=timeout), {
            "status": "not_ssh_transport"
        }
    directory = Path(tempfile.mkdtemp(prefix="yoke-linux-golden-diagnostics-"))
    client_log = directory / "ssh-client.log"
    client_log.touch(mode=0o600)
    secrets = getattr(control, "secret_values", ())
    started = datetime.now(timezone.utc)
    result = control._run(
        command, input_text=input_text, timeout=timeout, debug_log=client_log
    )
    finished = datetime.now(timezone.utc)
    client_log.write_text(_sanitize(client_log.read_text(errors="replace"), secrets))
    journal_command = shlex.join(
        [
            "sudo",
            "-n",
            "journalctl",
            "--no-pager",
            "--output=short-iso",
            "--unit=ssh.service",
            "--unit=sshd.service",
            "--since",
            started.isoformat(),
            "--until",
            finished.isoformat(),
        ]
    )
    journal = control._run(journal_command, timeout=20)
    journal_log = directory / "sshd-journal.log"
    journal_log.touch(mode=0o600)
    journal_log.write_text(_sanitize(journal.stdout + "\n" + journal.stderr, secrets))
    evidence = {
        "started_at": started.isoformat(),
        "completed_at": finished.isoformat(),
        "ssh_client_log": str(client_log),
        "sshd_journal_log": str(journal_log),
        "ssh_client_log_available": client_log.stat().st_size > 1,
        "sshd_journal_exit_code": journal.returncode,
        "sshd_journal_diagnostic": bounded_machine_qa_diagnostic(
            journal.stderr, secrets
        ),
        "recovery": "Inspect the retained transport and journal logs; an SSH exit code alone does not establish its cause.",
    }
    return result, evidence


def golden_timeout_result(
    control, result, diagnostics, operation, destination, elapsed, timeout
):
    """Keep partial-restore recovery beside the retained transport evidence."""
    return HostActionResult(
        False,
        {
            "reason": "linux_golden_operation_timeout",
            "transport_diagnostics": diagnostics,
            "operation": operation,
            "elapsed_seconds": elapsed,
            "timeout_seconds": timeout,
            "golden_baseline_path": destination,
            "exit_code": result.returncode,
            "stdout": bounded_machine_qa_diagnostic(
                result.stdout, getattr(control, "secret_values", ())
            ),
            "stderr": bounded_machine_qa_diagnostic(
                result.stderr, getattr(control, "secret_values", ())
            ),
            "detail": f"Linux golden {operation} timed out after {elapsed} seconds.",
            "recovery": (
                f"The remote archive process may still be running. Stop or wait for the {operation} targeting {destination} before retrying. "
                + (
                    f"Capture was not registered or sealed with probes; inspect {destination}/home.tar.gz and {destination}/manifest.json, and sibling .yoke-golden-* temporary directories. Remove only this capture's unregistered output after the process stops, or choose a new literal destination outside the home."
                    if operation == "capture"
                    else "The home may be partly restored; retry the existing sealed baseline after the process stops. Never capture a mixed home."
                )
            ),
        },
        "linux_golden_operation_timeout",
    )
