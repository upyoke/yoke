"""Approve a test's own machine request through its installed browser profile."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import subprocess
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from yoke_contracts.machine_qa_execution import GUI_SESSION_CONTEXT


@dataclass(frozen=True)
class BrowserApprovalResult:
    """Bounded result of one candidate-profile browser approval attempt."""

    ok: bool
    evidence: dict[str, Any]
    error_code: str | None = None


def _approval_url(verification_url: str, user_code: str, flow: dict) -> tuple[str, str]:
    parsed = urlsplit(verification_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in flow["paths"]
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("browser approval URL is not a supported HTTPS entry")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in flow["origins"]:
        raise ValueError("browser approval origin is not project-declared")
    code = user_code.strip()
    if len(code) > 256 or re.fullmatch(flow["code_pattern"], code) is None:
        raise ValueError("browser approval code has an invalid shape")
    complete = urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode({flow["query_parameter"]: code}),
            "",
        )
    )
    return complete, f"{parsed.scheme}://{parsed.netloc}"


def _cli(control: Any, *argv: str, deadline: float) -> tuple[bool, dict[str, Any]]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return False, {}
    options = {"timeout": remaining}
    if control.material.settings.get("os") == "macos":
        options["required_session_context"] = GUI_SESSION_CONTEXT
    try:
        result = control.run_command(
            [control.path_state.yoke_bin, "qa", "browser", *argv], **options
        )
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return False, {}
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        return False, {}
    return result.returncode == 0 and isinstance(data, dict), data if isinstance(
        data, dict
    ) else {}


def _failure(
    code: str, *, origin: str, machine: str, phase: str, human: bool = False
) -> BrowserApprovalResult:
    evidence: dict[str, Any] = {
        "browser": "candidate-daemon",
        "phase": phase,
        "site": origin,
        "machine": machine,
    }
    evidence["recovery"] = (
        "The operator must open this project's browser authorization window on the named test machine, sign in personally, prove the actual application signed in, and capture a new separate browser-profile baseline. Resume this case to generate a fresh approval link."
        if human
        else "Repair the named candidate browser phase, then rerun the same case; never log in or substitute an approval outside this flow."
    )
    if human:
        evidence["human_gate"] = {
            "reason": code,
            "site": origin,
            "machine": machine,
            "resume": "rerun the same case for a fresh flow",
        }
    return BrowserApprovalResult(False, evidence, code)


def approve_machine_from_profile(
    control: Any,
    *,
    verification_url: str,
    user_code: str,
    flow: dict,
    timeout_seconds: float = 300,
) -> BrowserApprovalResult:
    """Restore after installation, prove the approval screen, and press its control.

    The caller is the registered, leased Machine QA host adapter. Its candidate
    launcher and project-owned baseline are the only browser authority here.
    No password, login control, token paste, or alternate browser is used.
    """
    deadline = time.monotonic() + timeout_seconds
    machine = control.material.settings["resource_name"]
    try:
        expected_url, origin = _approval_url(verification_url, user_code, flow)
    except ValueError:
        return _failure(
            "machine_browser_context_invalid",
            origin="",
            machine=machine,
            phase="context",
        )
    project = control.material.project
    baseline = control.material.settings.get("browser_profile_baseline_path")
    if not baseline:
        return _failure(
            "browser_profile_sign_in_missing",
            origin=origin,
            machine=machine,
            phase="restore",
            human=True,
        )
    ok, status = _cli(
        control, "status", "--project", project, "--json", deadline=deadline
    )
    if not ok or not isinstance(status.get("profile"), dict):
        return _failure(
            "machine_browser_status_failed",
            origin=origin,
            machine=machine,
            phase="status",
        )
    setup = ["setup", "--project", project, "--json"]
    if status.get("profile", {}).get("status") != "authorized":
        setup.extend(["--profile-baseline", baseline])
    ok, prepared = _cli(control, *setup, deadline=deadline)
    if not ok or prepared.get("ok") is not True:
        return _failure(
            "machine_browser_profile_setup_failed",
            origin=origin,
            machine=machine,
            phase="setup",
        )
    steps = (
        {"action": "navigate", "route": expected_url, "timeout_ms": 30000},
        {
            "action": "assert",
            "target": flow["approval_target"],
            "check": "visible",
            "timeout_ms": 15000,
        },
        {
            "action": "click",
            "target": flow["approval_target"],
            "timeout_ms": 15000,
        },
    )
    for step in steps:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return _failure(
                "machine_browser_approval_timed_out",
                origin=origin,
                machine=machine,
                phase=step["action"],
            )
        step["timeout_ms"] = min(step["timeout_ms"], max(1, int(remaining * 1000)))
        ok, response = _cli(
            control,
            "step",
            "--project",
            project,
            "--base-url",
            origin,
            "--step-json",
            json.dumps(step),
            deadline=deadline,
        )
        data = response.get("data", {})
        phase = step["action"]
        if isinstance(data, dict) and data.get("authenticationWall") is True:
            return _failure(
                "browser_profile_sign_in_expired",
                origin=origin,
                machine=machine,
                phase=phase,
                human=True,
            )
        if (
            not ok
            or response.get("success") is not True
            or not isinstance(data, dict)
            or data.get("success") is not True
        ):
            return _failure(
                "machine_browser_approval_" + phase + "_failed",
                origin=origin,
                machine=machine,
                phase=phase,
            )
        observed = urlsplit(str(data.get("url", "")))
        if f"{observed.scheme}://{observed.netloc}" != origin:
            return _failure(
                "machine_browser_approval_destination_invalid",
                origin=origin,
                machine=machine,
                phase=phase,
            )
        if phase != "click" and str(data.get("url")) != expected_url:
            return _failure(
                "machine_browser_approval_context_changed",
                origin=origin,
                machine=machine,
                phase=phase,
            )
        if parse_qs(observed.query).get("status", [""])[0] in flow["rejected_statuses"]:
            return _failure(
                "machine_browser_approval_rejected",
                origin=origin,
                machine=machine,
                phase=phase,
            )
    return BrowserApprovalResult(
        True,
        {
            "browser": "candidate-daemon",
            "approval_entry": urlsplit(expected_url).path,
            "result_url": urlunsplit(
                (observed.scheme, observed.netloc, observed.path, "", "")
            ),
            "visible_control": flow["approval_target"],
            "profile_restored": prepared.get("profile_restore", {}).get(
                "restored", False
            ),
            "declaration_sha256": flow.get("declaration_sha256"),
            "required_sign_ins": flow.get("required_sign_ins", []),
        },
    )
