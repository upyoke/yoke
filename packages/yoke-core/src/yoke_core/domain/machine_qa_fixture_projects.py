"""Find and uninstall the Yoke projects a walk registered on its Test Machine.

Walk-start resets the Test Machine to its declared baseline, so every project
its Yoke config maps when the walk ends was installed during the walk. Each
checkout's linked worktrees are force-removed (their items are cancelled by
the control plane next), then ``yoke project uninstall`` removes the
checkout's registration, folder trust, Git hooks and installed layer.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.machine_config.schema_connections import (
    configured_active_env,
    same_universe_https_env,
)
from yoke_contracts.machine_config.schema_projects import (
    connection_project_maps,
    normalize_projects,
)

HOST_GIT = "/usr/bin/git"
_EVIDENCE_LIMIT = 400


class FixtureProjectDiscoveryError(RuntimeError):
    """The host's Yoke config cannot name the projects the walk registered."""


def discover_host_projects(control: Any) -> list[dict[str, Any]]:
    """Return the host's project mappings on its own active connection."""
    path = f"{control.home}/.yoke/config.json"
    text = control.read_text(path)
    if text is None:
        return []
    try:
        payload = json.loads(text)
        env = configured_active_env(payload)
        label = same_universe_https_env(payload, env) or env
        return normalize_projects(connection_project_maps(payload).get(label))
    except (ValueError, TypeError, RuntimeError) as exc:
        raise FixtureProjectDiscoveryError(
            f"fixture_projects_unreadable: {path} on the Test Machine does not "
            f"name its projects ({type(exc).__name__}: {exc}). Repair that file "
            "on the host or remove it, then rerun this walk-end"
        ) from exc


def _run(control: Any, argv: list[str], timeout: int) -> dict[str, Any]:
    completed = control.run_command(argv, timeout=timeout)
    return {
        "argv": argv,
        "exit_code": int(completed.returncode),
        "stdout": str(completed.stdout or "")[-_EVIDENCE_LIMIT:],
        "stderr": str(completed.stderr or "")[-_EVIDENCE_LIMIT:],
    }


def _linked_worktrees(listing: str, checkout: str) -> list[str]:
    paths = [
        line.removeprefix("worktree ")
        for line in listing.splitlines()
        if line.startswith("worktree ")
    ]
    return [path for path in paths if path.rstrip("/") != checkout.rstrip("/")]


def uninstall_host_project(
    control: Any, entry: dict[str, Any], *, timeout_seconds: int
) -> dict[str, Any]:
    """Remove one checkout's lanes and installed layer; return the evidence."""
    from yoke_core.domain.host_baseline_operations import _path_state

    checkout = str(entry["checkout"])
    result: dict[str, Any] = {
        "project_id": int(entry["project_id"]),
        "checkout": checkout,
        "removed_worktrees": [],
        "steps": [],
    }
    listing = control.run_command(
        [HOST_GIT, "-C", checkout, "worktree", "list", "--porcelain"],
        timeout=timeout_seconds,
    )
    if int(listing.returncode) != 0:
        return {**result, "uninstalled": False, "reason": "checkout_unreadable"}
    for path in _linked_worktrees(str(listing.stdout or ""), checkout):
        step = _run(
            control,
            [
                HOST_GIT,
                "-C",
                checkout,
                "worktree",
                "remove",
                "--force",
                "--force",
                path,
            ],
            timeout_seconds,
        )
        result["steps"].append(step)
        if step["exit_code"] == 0:
            result["removed_worktrees"].append(path)
    result["steps"].append(
        _run(control, [HOST_GIT, "-C", checkout, "worktree", "prune"], timeout_seconds)
    )
    uninstall = _run(
        control,
        [_path_state(control).yoke_bin, "project", "uninstall", "--json", checkout],
        timeout_seconds,
    )
    result["steps"].append(uninstall)
    if uninstall["exit_code"] != 0:
        return {**result, "uninstalled": False, "reason": "uninstall_failed"}
    return {**result, "uninstalled": True, "reason": None}


def uninstall_host_projects(control: Any, *, timeout_seconds: int) -> list[dict]:
    """Uninstall every project the host maps; one failure never stops the rest."""
    return [
        uninstall_host_project(control, entry, timeout_seconds=timeout_seconds)
        for entry in discover_host_projects(control)
    ]


__all__ = [
    "FixtureProjectDiscoveryError",
    "discover_host_projects",
    "uninstall_host_project",
    "uninstall_host_projects",
]
