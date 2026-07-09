"""DB-backed handoff run creation for deterministic project onboarding."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any, Callable, Mapping

from yoke_contracts.onboard_checklist import (
    BRANCH_CLONE_REMOTE,
    BRANCH_CREATE_REPO,
    BRANCH_LOCAL_CHECKOUT,
    BRANCH_SOURCE_DEV_ADMIN,
    SETUP_HANDOFF_ROW_ID,
    STATUS_BLOCKED,
    STATUS_CONFIGURED,
    STATUS_DEFERRED,
    STATUS_VERIFIED,
)

DispatchFn = Callable[[str, Mapping[str, Any], str | Path | None], Mapping[str, Any]]


def create_handoff(
    *,
    operation: str,
    root: Path,
    project: Mapping[str, Any],
    install: Mapping[str, Any],
    github_adoption: Mapping[str, Any] | None,
    config_path: str | Path | None,
    dispatch_fn: DispatchFn,
) -> dict[str, Any]:
    """Create/update the server-side checklist run and return handoff details."""
    payload = _payload(
        operation=operation,
        root=root,
        project=project,
        install=install,
        github_adoption=github_adoption,
    )
    result = dispatch_fn("onboard.checklist.run", payload, config_path)
    run_id = str(result.get("run_id") or "")
    command = _agent_command(root, run_id or "<run-id>")
    return {
        "run_id": run_id,
        "status": result.get("status"),
        "project_root": str(root),
        "project_id": int(project["id"]),
        "agent_command": command,
        "snapshot_sync": dict(install.get("snapshot_sync") or {}),
        "install_report": dict(install),
    }


def _payload(
    *,
    operation: str,
    root: Path,
    project: Mapping[str, Any],
    install: Mapping[str, Any],
    github_adoption: Mapping[str, Any] | None,
) -> dict[str, Any]:
    row_status, evidence, blocker = _row_updates(
        operation=operation,
        root=root,
        install=install,
        github_adoption=github_adoption,
    )
    return {
        "branch": _branch(operation),
        "project_id": int(project["id"]),
        "checkout_path": str(root),
        "github_repo": project.get("github_repo"),
        "row_status": row_status,
        "evidence": evidence,
        "blocker": blocker,
        "metadata": {
            "source_operation": operation,
            "install_report": dict(install),
            "github_adoption": dict(github_adoption or {}),
            "agent_command_template": _agent_command(root, "<run-id>"),
            "repair_commands": _repair_commands(install),
        },
    }


def _row_updates(
    *,
    operation: str,
    root: Path,
    install: Mapping[str, Any],
    github_adoption: Mapping[str, Any] | None,
) -> tuple[dict[str, str], dict[str, Any], dict[str, str]]:
    row_status = {
        "package-install": STATUS_VERIFIED,
        "machine-profile": STATUS_CONFIGURED,
        "yoke-connection": STATUS_VERIFIED,
        "project-permission": STATUS_VERIFIED,
        "project-source-choice": STATUS_VERIFIED,
        "project-identity": STATUS_VERIFIED,
        "checkout-binding": STATUS_VERIFIED,
        "deterministic-repo-substrate": STATUS_VERIFIED,
        SETUP_HANDOFF_ROW_ID: STATUS_CONFIGURED,
    }
    evidence: dict[str, Any] = {
        "project-source-choice": {"operation": operation},
        "checkout-binding": {"checkout": str(root), "project_id": int(install["project_id"])},
        "deterministic-repo-substrate": {"manifest": install.get("manifest")},
        SETUP_HANDOFF_ROW_ID: {"snapshot_sync": install.get("snapshot_sync")},
    }
    blocker: dict[str, str] = {}
    _apply_github_row(row_status, evidence, github_adoption)
    snapshot = install.get("snapshot_sync") or {}
    if snapshot.get("status") != "ok":
        row_status[SETUP_HANDOFF_ROW_ID] = STATUS_BLOCKED
        repair = snapshot.get("repair_command") or "yoke project snapshot sync"
        blocker[SETUP_HANDOFF_ROW_ID] = (
            f"Run `{repair}` before path-claim flows."
        )
    return row_status, evidence, blocker


def _apply_github_row(
    row_status: dict[str, str],
    evidence: dict[str, Any],
    github_adoption: Mapping[str, Any] | None,
) -> None:
    choice = str((github_adoption or {}).get("choice") or "skip")
    if choice in ("skip", "backlog-only"):
        row_status["machine-github-connection"] = STATUS_DEFERRED
    elif choice in ("temporary-only", "app-binding"):
        row_status["machine-github-connection"] = STATUS_CONFIGURED
    else:
        row_status["machine-github-connection"] = STATUS_VERIFIED
    evidence["machine-github-connection"] = {"github_adoption": choice}


def _branch(operation: str) -> str:
    return {
        "project.create": BRANCH_CREATE_REPO,
        "project.import": BRANCH_CLONE_REMOTE,
        "onboard.source-dev-admin": BRANCH_SOURCE_DEV_ADMIN,
    }.get(operation, BRANCH_LOCAL_CHECKOUT)


def _repair_commands(install: Mapping[str, Any]) -> dict[str, str]:
    snapshot = install.get("snapshot_sync") or {}
    command = snapshot.get("repair_command")
    return {"path_snapshot": str(command)} if command else {}


def _agent_command(root: Path, run_id: str) -> str:
    return shlex.join([
        "/yoke",
        "onboard-project",
        "--project-root",
        str(root),
        "--run-id",
        run_id,
    ])


__all__ = ["create_handoff"]
