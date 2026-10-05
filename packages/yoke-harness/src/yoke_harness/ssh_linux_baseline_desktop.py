"""Prove a Linux golden restores a working desktop before registering it."""

from __future__ import annotations

import json
import shlex

from yoke_harness.ssh_linux_reset_preconditions import DESKTOP_PROGRAM
from yoke_harness.test_machine_types import HostActionResult


def end_desktop(control) -> HostActionResult:
    program = (
        DESKTOP_PROGRAM
        + """
try:
    stop_desktop()
    print(json.dumps({"ok": True}))
except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
    print(json.dumps({"ok": False, "recovery": str(exc)}))
    raise SystemExit(69)
"""
    )
    try:
        result = control._run(
            shlex.join(["/usr/bin/python3", "-c", program]), timeout=60
        )
    except Exception as exc:
        return HostActionResult(
            False,
            {
                "recovery": f"Desktop termination raised {type(exc).__name__}; repair the SSH operation, then capture to a new destination."
            },
            "linux_desktop_stop_not_proved",
        )
    try:
        evidence = json.loads(result.stdout)
    except (ValueError, TypeError):
        evidence = {}
    if not isinstance(evidence, dict):
        evidence = {}
    ok = result.returncode == 0 and evidence.get("ok") is True
    if not ok:
        evidence.setdefault(
            "recovery", "Repair desktop termination, then capture to a new destination."
        )
    return HostActionResult(
        ok, evidence, None if ok else "linux_desktop_stop_not_proved"
    )


def prove_capture_roundtrip(
    control, destination, document, captured
) -> HostActionResult:
    from yoke_harness.ssh_linux_baseline import archive_operation, prove_linux_probes

    steps = []
    evidence = dict(captured.evidence)
    failed = None
    for name, action in (
        ("reset_roundtrip", lambda: archive_operation(control, "reset", destination)),
        ("restored_probes", lambda: prove_linux_probes(control, document)),
    ):
        result = action()
        steps.append({"name": name, "ok": result.ok, **result.evidence})
        if not result.ok:
            failed = (name, result)
            break
    if failed is None:
        try:
            try:
                frame = control.capture_screenshot()
            except Exception as exc:
                frame = HostActionResult(
                    False,
                    {
                        "recovery": f"Desktop capture raised {type(exc).__name__}; repair the capture operation, then capture to a new destination."
                    },
                    "desktop_screenshot_failed",
                )
            steps.append(
                {
                    "name": "desktop_frame",
                    "ok": frame.ok,
                    **{
                        k: v
                        for k, v in frame.evidence.items()
                        if k != "capture_artifact"
                    },
                }
            )
            if frame.ok:
                evidence.update(
                    {
                        k: v
                        for k, v in frame.evidence.items()
                        if k not in {"capture_artifact", "artifact_token"}
                    }
                )
            else:
                failed = ("desktop_frame", frame)
        finally:
            stopped = end_desktop(control)
            steps.append({"name": "desktop_end", "ok": stopped.ok, **stopped.evidence})
            if not stopped.ok and failed is None:
                failed = ("desktop_end", stopped)
    evidence["roundtrip_checks"] = steps
    if failed is not None:
        name, result = failed
        evidence.update(
            failing_step=name,
            step_error_code=result.error_code,
            recovery=result.evidence.get(
                "recovery",
                "Repair the named step, then capture to a new destination; this golden was not registered.",
            ),
        )
        return HostActionResult(False, evidence, "linux_golden_" + name + "_failed")
    return HostActionResult(True, evidence)
