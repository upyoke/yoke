"""Attribution required on a destructive migration apply.

A completed ``migration_audit`` row that omits session, actor, branch, or
commit is not an audit record. Callers that cannot establish those four
fields fail before any apply rather than writing nulls. Existing null rows
are left as they are — this module does not backfill.

``model_name`` on the same row is a declared migration model. Execution
lanes (including the unresolved-lane sentinel) are refused unless that
spelling is also a declared model, which is how the yoke default model
shares a name with the sentinel without the column becoming a lane dump.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from yoke_contracts.session_lane import (
    DEFAULT_LANE_METADATA,
    UNRESOLVED_EXECUTION_LANE,
)
from yoke_core.domain.migration_apply_contract import MigrationApplyError
from yoke_core.domain.migration_model_capability_defaults import DEFAULT_MODEL_NAME

ATTRIBUTION_FIELDS = (
    "session_id",
    "actor_id",
    "source_branch",
    "source_commit",
)

BOOT_BRANCH_WHEN_UNRESOLVED = "boot"


class IncompleteAttributionError(MigrationApplyError):
    """An apply that could not name who ran it, from which branch and commit."""


class LaneAsModelNameError(MigrationApplyError):
    """``model_name`` carried an execution lane instead of a migration model."""


def require_attribution(values: Mapping[str, Any]) -> Dict[str, str]:
    """Return the four attribution fields, or name every missing one."""
    missing = [
        name for name in ATTRIBUTION_FIELDS if not _present(values.get(name))
    ]
    if missing:
        listed = ", ".join(missing)
        copula = "is" if len(missing) == 1 else "are"
        raise IncompleteAttributionError(
            "Refuse to apply without attribution: "
            f"{listed} {copula} missing. Session, actor, branch, and commit "
            "are required."
        )
    return {name: str(values[name]).strip() for name in ATTRIBUTION_FIELDS}


def refuse_lane_as_model_name(
    model_name: Optional[str],
    *,
    declared_models: Iterable[str] = (),
    execution_lanes: Iterable[str] = (),
) -> str:
    """Return a model name that is not an undeclared execution lane."""
    value = (model_name or "").strip()
    if not value:
        raise LaneAsModelNameError(
            "model_name is missing; a declared migration model is required, "
            "not an execution lane"
        )
    declared = {str(name).strip() for name in declared_models if str(name).strip()}
    lanes = _known_execution_lanes(execution_lanes)
    if declared:
        if value not in declared:
            raise LaneAsModelNameError(
                f"model_name {value!r} is not a declared migration model"
            )
        return value
    if value in lanes and value != DEFAULT_MODEL_NAME:
        raise LaneAsModelNameError(
            f"model_name {value!r} is an execution lane, not a migration "
            "model"
        )
    return value


def collect_boot_attribution(
    *,
    applied_by: str,
    running_version: str,
    worktree: Optional[Path] = None,
) -> Dict[str, str]:
    """Attribution for the boot-converge apply, which has no harness session.

    The process identity is ``applied_by`` (typically ``boot-converge``).
    Branch and commit come from the checkout when git is there, otherwise
    the running artifact version and a boot branch marker. Empty on both
    sides still fails closed.
    """
    actor = (applied_by or "").strip()
    branch, commit = git_branch_and_commit(worktree or Path.cwd())
    return require_attribution(
        {
            "session_id": actor,
            "actor_id": actor,
            "source_branch": branch or BOOT_BRANCH_WHEN_UNRESOLVED,
            "source_commit": commit or (running_version or "").strip() or None,
        }
    )


def collect_operator_attribution(
    control_conn: Any,
    *,
    worktree: Optional[Path] = None,
) -> Dict[str, str]:
    """Attribution for a manual apply. Missing ambient identity fails closed."""
    from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id

    session_id = resolve_ambient_session_id()
    actor_id = lookup_session_actor_id(control_conn, session_id)
    branch, commit = git_branch_and_commit(worktree or Path.cwd())
    return require_attribution(
        {
            "session_id": session_id,
            "actor_id": actor_id,
            "source_branch": branch,
            "source_commit": commit,
        }
    )


def lookup_session_actor_id(
    control_conn: Any, session_id: Optional[str]
) -> Optional[str]:
    """``harness_sessions.actor_id`` for *session_id*, or ``None``."""
    from yoke_core.domain import db_backend

    if not session_id:
        return None
    try:
        placeholder = "%s" if db_backend.connection_is_postgres(control_conn) else "?"
        row = control_conn.execute(
            f"SELECT actor_id FROM harness_sessions WHERE session_id = {placeholder}",
            (session_id,),
        ).fetchone()
    except db_backend.operational_error_types(control_conn):
        return None
    if row is None or row[0] is None:
        return None
    return str(row[0])


def git_branch_and_commit(
    worktree_path: Path,
) -> tuple[Optional[str], Optional[str]]:
    if not worktree_path or not Path(worktree_path).exists():
        return None, None
    branch = _git_capture(worktree_path, ["branch", "--show-current"])
    commit = _git_capture(worktree_path, ["rev-parse", "HEAD"])
    return branch, commit


def _git_capture(worktree_path: Path, argv: list[str]) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(worktree_path), *argv],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _known_execution_lanes(extra: Iterable[str]) -> frozenset[str]:
    lanes = {UNRESOLVED_EXECUTION_LANE, *DEFAULT_LANE_METADATA}
    lanes.update(str(name).strip() for name in extra if str(name).strip())
    return frozenset(lanes)


def _present(value: Any) -> bool:
    if value is None:
        return False
    return bool(str(value).strip())


__all__ = [
    "ATTRIBUTION_FIELDS",
    "BOOT_BRANCH_WHEN_UNRESOLVED",
    "IncompleteAttributionError",
    "LaneAsModelNameError",
    "collect_boot_attribution",
    "collect_operator_attribution",
    "git_branch_and_commit",
    "lookup_session_actor_id",
    "refuse_lane_as_model_name",
    "require_attribution",
]
