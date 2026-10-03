"""Framed shell resolution evidence, independent of login startup chatter."""

from __future__ import annotations

import shlex
import uuid

from yoke_contracts.machine_qa_failures import bounded_machine_qa_diagnostic


RESET_TOOLS = ("yoke", "uv", "uvx")


def probe_tool_resolution(control, surface: str, tool: str) -> dict:
    """Resolve one executable; an incomplete probe never proves absence."""
    marker = "YOKE_TOOL_PROBE_" + uuid.uuid4().hex
    script = (
        f"resolved=$(command -v {shlex.quote(tool)}); resolution_exit=$?; "
        f"printf '\\n%s\\t%s\\t%s\\n' {shlex.quote(marker)} "
        '"$resolution_exit" "$resolved"; exit 0'
    )
    result = control._run(
        shlex.join([control.shell, "-lic" if surface == "login" else "-c", script]),
        timeout=20,
    )
    frames = [
        line.split("\t", 2)
        for line in result.stdout.splitlines()
        if line.startswith(marker + "\t")
    ]
    state, reason, path, resolution_exit = "probe-failed", "frame_missing", None, None
    if len(frames) == 1 and len(frames[0]) == 3:
        _, code, value = frames[0]
        if code.isdecimal():
            resolution_exit = int(code)
            if resolution_exit == 1 and not value:
                state, reason = "absent", None
            elif resolution_exit == 0 and value.startswith("/"):
                state, reason, path = "present", None, value
            else:
                reason = "unexpected_resolution"
        else:
            reason = "invalid_resolution_exit"
    elif frames:
        reason = "frame_invalid"
    if result.returncode:
        state, reason = "probe-failed", "shell_or_transport_failed"
    return {
        "state": state,
        "exit_code": result.returncode,
        "resolution_exit_code": resolution_exit,
        "resolved_path": (
            bounded_machine_qa_diagnostic(path, control.secret_values) if path else None
        ),
        "stdout": bounded_machine_qa_diagnostic(result.stdout, control.secret_values),
        "stderr": bounded_machine_qa_diagnostic(result.stderr, control.secret_values),
        "failure_reason": reason,
    }


def probe_reset_tools(control) -> dict[str, dict[str, dict]]:
    """Retain every tool's result on both user entry surfaces."""
    return {
        surface: {
            tool: probe_tool_resolution(control, surface, tool) for tool in RESET_TOOLS
        }
        for surface in ("login", "ssh")
    }


def tools_present(observed: dict, tools=RESET_TOOLS) -> bool | None:
    """Report observed presence, or unknown when a required probe failed."""
    states = [surface[tool]["state"] for surface in observed.values() for tool in tools]
    if "present" in states:
        return True
    return None if "probe-failed" in states else False
