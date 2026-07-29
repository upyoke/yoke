"""Shared declarative vocabulary for the installer Machine QA plan."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from yoke_cli.config.onboard_destinations import (
    DESTINATION_LOCAL,
    DESTINATION_OVERRIDE,
)
from yoke_contracts.api_urls import HOSTED_STAGE_PLATFORM_URL

from yoke_core.domain.installer_campaign_recipe_operations import (
    installed_yoke,
    operation,
    prepared_path,
)
from yoke_core.domain.machine_qa_fixture_constants import (
    DISTRIBUTION_URL,
    YOKE_BIN,
)


FRESH_HOST = "fresh-host"
SHELL_PRECONFIGURED = "shell-preconfigured"
DUAL_HOST_BASELINES = [FRESH_HOST, SHELL_PRECONFIGURED]

PUBLIC_STAGE_INSTALL = (
    f"/usr/bin/curl -fsSL {DISTRIBUTION_URL}/install | "
    f"/usr/bin/env YOKE_INSTALL_BASE_URL={DISTRIBUTION_URL} "
    "YOKE_CHANNEL=latest /bin/sh"
)
PUBLIC_STAGE_WELCOME = (
    f"/usr/bin/curl -fsSL {DISTRIBUTION_URL}/install | "
    "/usr/bin/env HOME=/var/empty XDG_BIN_HOME=/var/empty/.local/bin "
    "PATH=/usr/bin:/bin:/usr/sbin:/sbin "
    f"YOKE_INSTALL_BASE_URL={DISTRIBUTION_URL} "
    "YOKE_CHANNEL=latest /bin/sh"
)
PUBLIC_STAGE_INSTALL_LOCAL = (
    f"/usr/bin/curl -fsSL {DISTRIBUTION_URL}/install | "
    f"/usr/bin/env YOKE_INSTALL_BASE_URL={DISTRIBUTION_URL} "
    f"YOKE_CHANNEL=latest {DESTINATION_OVERRIDE}={DESTINATION_LOCAL} /bin/sh"
)
HOSTED_STAGE_ONBOARD = (
    f"{YOKE_BIN} onboard --connect {HOSTED_STAGE_PLATFORM_URL} "
    "--project-mode machine-only"
)
PATH_REPAIR_COMMAND = f"{YOKE_BIN} path fix --yes --json"

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
HOSTED_CONNECTED_TEXT = ("Yoke token connected.",)
MACHINE_GITHUB_TEXT = ("Connect GitHub?",)

SECRET_SAFE_POST_CHECKS = (
    "secret_free",
    "no_text:Traceback",
)
BROWSER_PRIMARY_POST_CHECKS = (
    *SECRET_SAFE_POST_CHECKS,
    "no_text:Paste your Yoke API token.",
)

CHOOSE_STAGE_KEYS = ("Down", "Down", "Down", "Enter")
CHOOSE_BACKLOG_KEYS = ("Down", "Enter")
CHOOSE_MACHINE_ONLY_KEYS = ("Down", "Down", "Down", "Down", "Enter")


def action(
    step: str,
    *keys: str,
    capture: bool = True,
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
    if ready_text:
        row["ready_text"] = list(ready_text)
    if ready_timeout_seconds is not None:
        row["ready_timeout_seconds"] = ready_timeout_seconds
    if wait_seconds is not None:
        row["wait_seconds"] = wait_seconds
    return row


def transition(
    step: str,
    *keys: str,
    ready_text: Sequence[str] = (),
    ready_timeout_seconds: float | None = None,
    wait_seconds: float | None = None,
) -> dict[str, Any]:
    """Send input at a grounded source screen without taking a screenshot."""
    return action(
        step,
        *keys,
        capture=False,
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
    """Install the public Stage release with optional honest machine prep."""
    operations: list[dict[str, Any]] = []
    if clear_auth:
        operations.append(operation("machine.yoke-auth-clear"))
    operations.append(installed_yoke(evidence_name=evidence_name))
    if path_ready:
        operations.append(prepared_path(evidence_name=evidence_name))
    return operations


__all__ = [
    "APPLY_SUCCESS_TEXT",
    "BROWSER_APPROVAL_TEXT",
    "BROWSER_PRIMARY_POST_CHECKS",
    "CHOOSE_BACKLOG_KEYS",
    "CHOOSE_MACHINE_ONLY_KEYS",
    "CHOOSE_STAGE_KEYS",
    "DUAL_HOST_BASELINES",
    "FRESH_HOST",
    "HOSTED_CONNECTED_TEXT",
    "HOSTED_STAGE_ONBOARD",
    "MACHINE_GITHUB_TEXT",
    "PARENT_HANDOFF_TEXT",
    "PATH_REPAIR_COMMAND",
    "PUBLIC_STAGE_INSTALL",
    "PUBLIC_STAGE_INSTALL_LOCAL",
    "PUBLIC_STAGE_WELCOME",
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
