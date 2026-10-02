"""Shared declarative vocabulary for the installer Machine QA plan."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from yoke_cli.config.onboard_destinations import (
    DESTINATION_LOCAL,
    DESTINATION_OVERRIDE,
)

from yoke_core.domain.installer_campaign_recipe_operations import (
    installed_yoke,
    operation,
    prepared_path,
)
from yoke_core.domain.machine_qa_fixture_constants import (
    YOKE_BIN,
)


FRESH_HOST = "fresh-host"
SHELL_PRECONFIGURED = "shell-preconfigured"
DUAL_HOST_BASELINES = [FRESH_HOST, SHELL_PRECONFIGURED]

PUBLIC_INSTALL = (
    "/usr/bin/curl -fsSL {{installer_base_url}}/install | "
    "/usr/bin/env YOKE_INSTALL_BASE_URL={{installer_base_url}} "
    f"YOKE_CHANNEL={{{{release_channel}}}} {DESTINATION_OVERRIDE}={{{{app_url}}}} "
    "/bin/sh"
)
PUBLIC_WELCOME = (
    "/usr/bin/curl -fsSL {{installer_base_url}}/install | "
    "/usr/bin/env HOME=/var/empty XDG_BIN_HOME=/var/empty/.local/bin "
    "PATH=/usr/bin:/bin:/usr/sbin:/sbin "
    "YOKE_INSTALL_BASE_URL={{installer_base_url}} "
    "YOKE_CHANNEL={{release_channel}} /bin/sh"
)
PUBLIC_INSTALL_LOCAL = (
    "/usr/bin/curl -fsSL {{installer_base_url}}/install | "
    "/usr/bin/env YOKE_INSTALL_BASE_URL={{installer_base_url}} "
    f"YOKE_CHANNEL={{{{release_channel}}}} {DESTINATION_OVERRIDE}={DESTINATION_LOCAL} /bin/sh"
)
HOSTED_ONBOARD = (
    f"{YOKE_BIN} onboard --connect {{{{app_url}}}} --project-mode machine-only"
)
PATH_REPAIR_COMMAND = f"{YOKE_BIN} path fix --yes --json"

# These are Yoke's hosted approval steps, carried in each case action.
MACHINE_BROWSER_APPROVAL = {
    "origins": [HOSTED_STAGE_PLATFORM_URL],
    "paths": ["/connect", "/machine"],
    "url_label": "Open:",
    "code_label": "One-time code:",
    "code_pattern": "[A-Z0-9]{4}-[A-Z0-9]{4}",
    "query_parameter": "user_code",
    "approval_target": 'role=button[name="Approve machine"]',
    "rejected_statuses": [
        "denied",
        "expired",
        "missing",
        "not_admin",
        "not_member",
        "used",
    ],
    "denial_text": [
        "authorization denied in the browser",
        "authorization expired",
        "hosted authorization expired",
        "this machine was denied in the browser",
    ],
}

BROWSER_APPROVAL_TEXT = (
    "Sign in and choose an organization.",
    "Approve this machine in your browser, then continue here.",
    "One-time code:",
    "Open:",
)
REVIEW_TEXT = (
    "Review what Yoke will save.",
    "Apply",
)
APPLY_SUCCESS_TEXT = (
    "Setup complete.",
    "Everything in the Review plan was applied.",
    "Report:",
)
PARENT_HANDOFF_TEXT = (
    "Next: make it execution-ready.",
    "run /yoke onboard",
)
PATH_READY_TEXT = ("Yoke is already on your PATH.",)
MACHINE_GITHUB_TEXT = ("Connect GitHub?",)
PROJECT_MODE_TEXT = ("Set up a project.", "Where's the code?")

SECRET_SAFE_POST_CHECKS = (
    "secret_free",
    "no_text:Traceback",
)
BROWSER_PRIMARY_POST_CHECKS = (
    *SECRET_SAFE_POST_CHECKS,
    "no_text:Paste your Yoke API token.",
)

CHOOSE_BACKLOG_KEYS = ("Down", "Enter")
CHOOSE_MACHINE_ONLY_KEYS = ("Down", "Down", "Down", "Down", "Enter")


def action(
    step: str,
    *keys: str,
    capture: bool = True,
    completion_text: Sequence[str] = (),
    gate_timeout_seconds: float | None = None,
    operator_gate: str | None = None,
    ready_text: Sequence[str] = (),
    ready_timeout_seconds: float | None = None,
    wait_seconds: float | None = None,
) -> dict[str, Any]:
    """Build one bounded terminal action."""
    row: dict[str, Any] = {"step": step}
    if keys:
        row["keys"] = list(keys)
    if not capture:
        row["capture"] = False
    if operator_gate is not None:
        row["operator_gate"] = operator_gate
        if operator_gate == "machine_browser_approval":
            from copy import deepcopy

            row["browser_approval"] = deepcopy(MACHINE_BROWSER_APPROVAL)
    if completion_text:
        row["completion_text"] = list(completion_text)
    if gate_timeout_seconds is not None:
        row["gate_timeout_seconds"] = gate_timeout_seconds
    if ready_text:
        row["ready_text"] = list(ready_text)
    if ready_timeout_seconds is not None:
        from yoke_core.domain.machine_qa_action_readiness_contract import (
            bound_ready_timeout_seconds,
        )

        row["ready_timeout_seconds"] = bound_ready_timeout_seconds(
            ready_timeout_seconds
        )
    if wait_seconds is not None:
        row["wait_seconds"] = wait_seconds
    return row


def transition(
    step: str,
    *keys: str,
    completion_text: Sequence[str] = (),
    gate_timeout_seconds: float | None = None,
    operator_gate: str | None = None,
    ready_text: Sequence[str] = (),
    ready_timeout_seconds: float | None = None,
    wait_seconds: float | None = None,
) -> dict[str, Any]:
    """Send input at a grounded source screen without taking a screenshot."""
    return action(
        step,
        *keys,
        capture=False,
        completion_text=completion_text,
        gate_timeout_seconds=gate_timeout_seconds,
        operator_gate=operator_gate,
        ready_text=ready_text,
        ready_timeout_seconds=ready_timeout_seconds,
        wait_seconds=wait_seconds,
    )


def terminal_recipe(
    *,
    actions: Sequence[Mapping[str, Any]],
    expected_text: Iterable[str],
    capture_checkpoints: Iterable[str],
    notes: str,
    setup_operations: Sequence[Mapping[str, Any]] = (),
    post_checks: Iterable[str] = SECRET_SAFE_POST_CHECKS,
    execution_mode: str = "terminal",
    expected_return_codes: Sequence[int] = (0,),
    start_delay: float = 3.0,
    step_delay: float = 3.0,
) -> dict[str, Any]:
    """Build the registered terminal-recipe shape without fixture secrets."""
    return {
        "actions": [dict(row) for row in actions],
        "capture_checkpoints": list(capture_checkpoints),
        "execution_mode": execution_mode,
        "expected_return_codes": list(expected_return_codes),
        "expected_text": list(expected_text),
        "max_wall_seconds": 1200,
        "notes": notes,
        "post_checks": list(post_checks),
        "setup_operations": [dict(row) for row in setup_operations],
        "start_delay": start_delay,
        "step_delay": step_delay,
    }


def terminal_case(
    position: int,
    case_key: str,
    method_id: str,
    *,
    instructions: str,
    expected_outcome: str,
    method_config: Mapping[str, Any],
    entry_surface: str,
    required_completion: str,
    host_baselines: Sequence[str] = (),
) -> dict[str, Any]:
    """Build one complete Terminal method case."""
    return {
        "position": position,
        "case_key": case_key,
        "method_id": method_id,
        "instructions": instructions,
        "expected_outcome": expected_outcome,
        "method_config": dict(method_config),
        "host_baselines": list(host_baselines),
        "entry_surface": entry_surface,
        "required_completion": required_completion,
    }


def machine_case(
    position: int,
    case_key: str,
    *,
    instructions: str,
    expected_outcome: str,
    method_config: Mapping[str, Any],
    host_baselines: Sequence[str] = (),
) -> dict[str, Any]:
    """Build one complete Machine state check case."""
    return {
        "position": position,
        "case_key": case_key,
        "method_id": "machine-state-check",
        "instructions": instructions,
        "expected_outcome": expected_outcome,
        "method_config": dict(method_config),
        "host_baselines": list(host_baselines),
        "entry_surface": None,
        "required_completion": None,
    }


def current_release_setup(
    evidence_name: str,
    *,
    clear_auth: bool = False,
    path_ready: bool = False,
) -> list[dict[str, Any]]:
    """Install the public bound release with optional honest machine prep."""
    operations: list[dict[str, Any]] = []
    if clear_auth:
        operations.append(operation("machine.yoke-auth-clear"))
    operations.append(
        installed_yoke(
            evidence_name=evidence_name,
            base_url="{{installer_base_url}}",
            channel="{{release_channel}}",
        )
    )
    if path_ready:
        operations.append(prepared_path(evidence_name=evidence_name))
    return operations


__all__ = [
    "APPLY_SUCCESS_TEXT",
    "BROWSER_APPROVAL_TEXT",
    "BROWSER_PRIMARY_POST_CHECKS",
    "CHOOSE_BACKLOG_KEYS",
    "CHOOSE_MACHINE_ONLY_KEYS",
    "DUAL_HOST_BASELINES",
    "FRESH_HOST",
    "HOSTED_ONBOARD",
    "MACHINE_GITHUB_TEXT",
    "PARENT_HANDOFF_TEXT",
    "PATH_REPAIR_COMMAND",
    "PUBLIC_INSTALL",
    "PUBLIC_INSTALL_LOCAL",
    "PUBLIC_WELCOME",
    "REVIEW_TEXT",
    "SECRET_SAFE_POST_CHECKS",
    "SHELL_PRECONFIGURED",
    "action",
    "current_release_setup",
    "machine_case",
    "terminal_case",
    "terminal_recipe",
    "transition",
]
