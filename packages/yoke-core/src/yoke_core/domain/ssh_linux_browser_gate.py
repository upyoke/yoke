"""The Linux recipe's browser approval step and its desktop screenshot."""

from __future__ import annotations

from yoke_core.domain.machine_qa_operator_gate import (
    run_machine_browser_approval_with_io,
)
from yoke_core.domain.machine_qa_setup_exit import marker_exit_code
from yoke_core.domain.ssh_mac_terminal_recipe_support import send_recipe_keys
from yoke_harness.ssh_linux_browser_approval import (
    approve_machine_in_desktop_chromium,
)
from yoke_harness.test_machine_types import HostActionResult


def checkpoint(control, rows):
    """Attach a desktop screenshot to the last step, or name why it failed."""
    try:
        rows[-1].update(control.capture_terminal_checkpoint())
    except RuntimeError as exc:
        return HostActionResult(
            False,
            {"steps": rows, "recovery": str(exc)},
            "desktop_screenshot_failed",
        )
    return None


def run_browser_gate(control, terminal, action, rows, allowed_operator_urls, progress):
    """Hand the installer's approval to desktop Chromium; refuse with its reason."""
    gate = run_machine_browser_approval_with_io(
        read_transcript=terminal.transcript,
        send_keys=lambda keys: send_recipe_keys(
            control._run, backend="tmux", session=terminal.session, keys=keys
        ),
        read_exit_code=marker_exit_code,
        action=action,
        progress_callback=progress,
        allowed_base_urls=allowed_operator_urls,
        browser="Chromium",
        approve_browser=lambda url, code: approve_machine_in_desktop_chromium(
            control, verification_url=url, user_code=code
        ),
    )
    rows.append(
        {
            "key": str(action["step"]),
            "reached": gate.ok,
            "transcript": gate.transcript,
            "operator_gate": action["operator_gate"],
            "browser_approval": gate.browser_evidence,
            "browser_automation_error_code": gate.browser_automation_error_code,
        }
    )
    if gate.ok:
        return None
    if gate.step_evidence is not None:
        return HostActionResult(
            False,
            {
                **gate.step_evidence,
                "steps": rows,
                "operator_gate": action["operator_gate"],
                "browser_approval": gate.browser_evidence,
            },
            gate.error_code,
        )
    return HostActionResult(
        False,
        {
            "steps": rows,
            "operator_gate": action["operator_gate"],
            "browser_approval": gate.browser_evidence,
            "recovery": "Read browser_approval for the desktop Chromium outcome, "
            "repair the named step on the test machine, then rerun the case.",
        },
        gate.error_code,
    )


__all__ = ["checkpoint", "run_browser_gate"]
