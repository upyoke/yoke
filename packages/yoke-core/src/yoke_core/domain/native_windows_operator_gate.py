"""The native Windows recipe's operator gate step.

A browser approval runs in the operator identity's browser: the installer runs
in the interactive desktop (``WindowsTerminal.launch``'s scheduled task) with
``BROWSER`` set to ``yoke browser open``, and the approval driver runs
``yoke browser devtools`` on the host over SSH through the installed Yoke's
Python. DevTools listens on loopback, so it needs no port forwarding.
Admission gates need an owner machine home that only POSIX fixtures build, so
they refuse by name here.
"""

from __future__ import annotations

import subprocess

from yoke_contracts.runtime_ports.identity_browser_approval import (
    get_identity_browser_approval,
)
from yoke_contracts.runtime_ports.ssh_windows_host_operations import (
    get_ssh_windows_host_operations,
)
from yoke_contracts.test_machine_types import HostActionResult
from yoke_core.domain.machine_qa_human_gate import run_operator_gate_with_io
from yoke_core.domain.machine_qa_operator_gate_contract import (
    gate_needs_desktop_browser,
)
from yoke_core.domain.machine_qa_setup_exit import marker_exit_code

ADMISSION_UNSUPPORTED = "native_windows_admission_gate_unsupported"


def _refuse_admission(arguments):
    return subprocess.CompletedProcess(
        list(arguments),
        69,
        "",
        f"{ADMISSION_UNSUPPORTED}: admission gates run as an owner machine home "
        "that only POSIX fixtures build; run this admission case on a Linux or "
        "macOS test machine.",
    )


def run_operator_gate(
    control, terminal, action, rows, allowed_operator_urls, progress, reauthorize
):
    """Run the action's gate against the native console; None when it passed."""
    approve = get_identity_browser_approval().approve_machine_in_identity_browser
    host_command = get_ssh_windows_host_operations().yoke_python_command
    gate = run_operator_gate_with_io(
        read_transcript=terminal.transcript,
        send_keys=lambda keys: all(terminal.send(key, submit=False) for key in keys),
        read_exit_code=marker_exit_code,
        action=action,
        progress_callback=progress,
        allowed_base_urls=allowed_operator_urls,
        browser="Chromium",
        approve_browser=lambda url, code: approve(
            control._run,
            verification_url=url,
            user_code=code,
            reauthorize_command=reauthorize,
            yoke_bin=control.path_state.yoke_bin,
            secrets=getattr(control, "secret_values", ()),
            host_command=host_command,
        ),
        run_yoke=_refuse_admission,
        terminal_location=(
            f"the native console window titled {terminal.token} on the test "
            "machine's desktop"
        ),
    )
    row = {
        "key": str(action["step"]),
        "reached": gate.ok,
        "transcript": gate.transcript,
        "operator_gate": action["operator_gate"],
        "browser_approval": gate.browser_evidence,
        "browser_automation_error_code": gate.browser_automation_error_code,
        **({"gate_evidence": gate.step_evidence} if gate.step_evidence else {}),
    }
    rows.append(row)
    if not gate.ok:
        return HostActionResult(
            False,
            {
                **(gate.step_evidence or {}),
                "steps": rows,
                "operator_gate": action["operator_gate"],
                "browser_approval": gate.browser_evidence,
                "recovery": "Read browser_approval for the identity browser "
                "outcome, repair the named step on the test machine, then rerun "
                "the case.",
            },
            gate.error_code,
        )
    if gate_needs_desktop_browser(action):
        # A browser step leaves visual proof whether or not it is a checkpoint.
        row.update(terminal.capture_window())
    return None


__all__ = ["ADMISSION_UNSUPPORTED", "run_operator_gate"]
