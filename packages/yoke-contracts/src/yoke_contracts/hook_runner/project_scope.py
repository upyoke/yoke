"""Resolve hook project membership from the executing machine's checkout map."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yoke_contracts.machine_config import runtime as machine_config
from yoke_contracts.machine_config.checkout import main_checkout
from yoke_contracts.machine_config.schema_projects import (
    mapped_checkouts,
    project_entry_for_checkout,
)


def workspace_path_candidates(payload: dict[str, Any]) -> list[str]:
    """Read harness workspace facts in their shared precedence order."""
    roots = payload.get("workspace_roots")
    candidates = (
        [r for r in roots if isinstance(r, str) and r.strip()]
        if isinstance(roots, list)
        else []
    )
    for key in ("cwd", "workspace", "project_dir"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value)
    return candidates


def project_id_for_root(root: str | Path) -> int | None:
    """Find a registered checkout, never a connection or a parent Git repo."""
    if not root or not machine_config.config_path().is_file():
        return None
    path = Path(root).expanduser().resolve()
    if not path.is_dir():
        return None
    config = machine_config.load_config()
    primary = main_checkout(path)
    if any((parent / ".git").exists() for parent in (path, *path.parents)):
        # A nested independent repository must not inherit the outer mapping.
        return next(
            (
                project_id
                for checkout, project_id in mapped_checkouts(config)
                if Path(checkout).expanduser().resolve() == primary
            ),
            None,
        )
    return project_entry_for_checkout(config, primary).get("project_id")


def project_id_for_payload(payload: dict[str, Any]) -> int | None:
    """Classify the actual command directory before the session workspace."""
    for source in (
        payload.get("tool_input"),
        payload.get("toolInput"),
        payload.get("input"),
        payload,
    ):
        if isinstance(source, dict):
            for key in ("workdir", "working_directory"):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    return project_id_for_root(value)
    for value in workspace_path_candidates(payload):
        project_id = project_id_for_root(value)
        if project_id is not None:
            return project_id
    return None


class HookProjectScopeUnavailable(RuntimeError):
    """The hook's project membership could not be resolved."""


@dataclass(frozen=True)
class HookProjectScope:
    """One hook request's project membership, resolved once and passed on.

    Resolution can read the machine config and ask Git for the main
    checkout, so a request resolves it once at entry and every consumer
    reads this value. A failed resolution is kept, not raised, so each
    consumer still refuses with the same ``hook_scope_unavailable`` reason.
    """

    project_id: int | None = None
    failure: str = ""

    def require_project_id(self) -> int | None:
        """Return the project id, or raise the recorded resolution failure."""
        if self.failure:
            raise HookProjectScopeUnavailable(self.failure)
        return self.project_id


def resolve_hook_project_scope(payload: dict[str, Any]) -> HookProjectScope:
    """Resolve a hook payload's project membership exactly once."""
    try:
        return HookProjectScope(project_id=project_id_for_payload(payload))
    except (ValueError, OSError, RuntimeError) as exc:
        return HookProjectScope(failure=str(exc))
