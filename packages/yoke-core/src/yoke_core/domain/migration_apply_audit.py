"""Audit-row persistence helpers for governed migration apply.

``actor_id`` / ``worktree`` / ``source_branch`` / ``source_commit`` /
``integration_target`` / ``change_class`` onto live-apply audit rows.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.migration_apply_contract import (
    STATE_PLANNED,
    STATE_REHEARSED,
    _now,
)

if TYPE_CHECKING:
    pass

PROVENANCE_COLUMNS = (
    "actor_id",
    "worktree",
    "source_branch",
    "source_commit",
    "integration_target",
    "change_class",
)

DESCRIPTION_BASE = "two-unit apply contract (governed)"


def _operational_error_types(conn) -> tuple:
    return db_backend.operational_error_types(conn)


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _insert_audit_row(
    audit_conn: Any,
    *,
    name: str,
    model_name: str,
    project_id: int,
    session_id: Optional[str],
    test_copy_path: Optional[str],
    tables: List[str],
    description: Optional[str] = None,
) -> int:
    now = _now()
    p = _placeholder(audit_conn)
    expected_deltas_json = json.dumps({t: 0 for t in tables})
    cur = audit_conn.execute(
        "INSERT INTO migration_audit "
        "(migration_name, description, tables_declared, expected_deltas, "
        "pre_row_counts, pre_fk_violations, backup_path, started_at, "
        "state, model_name, project_id, session_id, test_copy_path) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}) RETURNING id",
        (
            name,
            description or DESCRIPTION_BASE,
            json.dumps(tables),
            expected_deltas_json,
            json.dumps({}),
            0,
            "",
            now,
            STATE_PLANNED,
            model_name,
            project_id,
            session_id,
            test_copy_path,
        ),
    )
    audit_id = int(cur.fetchone()[0])
    audit_conn.commit()
    return audit_id


def _update_audit_state(
    audit_conn: Any,
    audit_id: int,
    state: str,
    *,
    extra: Optional[Mapping[str, Any]] = None,
) -> None:
    p = _placeholder(audit_conn)
    sets = [f"state = {p}"]
    values: List[Any] = [state]
    for column, value in (extra or {}).items():
        sets.append(f"{column} = {p}")
        values.append(value)
    values.append(audit_id)
    audit_conn.execute(
        f"UPDATE migration_audit SET {', '.join(sets)} WHERE id = {p}",
        tuple(values),
    )
    audit_conn.commit()


def _latest_rehearsed_row(
    audit_conn: Any, identifier: str, model_name: str, *, project_id: int
) -> Optional[Dict[str, Any]]:
    try:
        p = _placeholder(audit_conn)
        row = audit_conn.execute(
            "SELECT id, state, source_fingerprint, rehearsed_at, "
            "baseline_verify_result, author_verify_result, test_copy_path, "
            "description "
            f"FROM migration_audit WHERE migration_name = {p} "
            f"AND project_id = {p} "
            f"AND COALESCE(model_name, {p}) = {p} "
            f"AND state = {p} ORDER BY id DESC LIMIT 1",
            (identifier, project_id, model_name, model_name, STATE_REHEARSED),
        ).fetchone()
    except _operational_error_types(audit_conn):
        return None
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# Override-marker helpers — keep description as the persistence channel so no
# migration_audit schema migration is required.
# ---------------------------------------------------------------------------


def build_live_apply_provenance(
    *,
    control_conn: Any,
    session_id: Optional[str],
    worktree_path: Path,
    profile: Mapping[str, Any],
) -> Dict[str, Optional[str]]:
    """Collect the accountable provenance for a live-apply audit row.

    Returns a dict keyed by :data:`PROVENANCE_COLUMNS` columns. Values are
    nullable strings — missing signals fall back to ``None`` rather than
    failing the apply, but the column shape is stable so downstream queries
    can rely on it.
    """
    actor_id = _resolve_session_actor_id(control_conn, session_id)
    worktree_str = str(worktree_path) if worktree_path else None
    branch, commit = _git_branch_and_commit(worktree_path)
    integration_target = _resolve_integration_target(profile)
    change_class = _resolve_change_class(profile)
    return {
        "actor_id": actor_id,
        "worktree": worktree_str,
        "source_branch": branch,
        "source_commit": commit,
        "integration_target": integration_target,
        "change_class": change_class,
    }


def set_audit_provenance(
    audit_conn: Any,
    audit_id: int,
    provenance: Mapping[str, Optional[str]],
) -> None:
    """Persist provenance columns on a migration_audit row, best-effort.

    Unknown columns (e.g., a pre-migration authoritative DB that has not yet
    grown the provenance columns) are silently skipped on
    the connection's operational DB error type so live-apply still proceeds.
    """
    sets: List[str] = []
    values: List[Any] = []
    p = _placeholder(audit_conn)
    for column in PROVENANCE_COLUMNS:
        if column not in provenance:
            continue
        sets.append(f"{column} = {p}")
        values.append(provenance[column])
    if not sets:
        return
    values.append(audit_id)
    try:
        audit_conn.execute(
            f"UPDATE migration_audit SET {', '.join(sets)} WHERE id = {p}",
            tuple(values),
        )
        audit_conn.commit()
    except _operational_error_types(audit_conn):
        return


def _resolve_session_actor_id(
    control_conn: Any,
    session_id: Optional[str],
) -> Optional[str]:
    if not session_id:
        return None
    try:
        p = _placeholder(control_conn)
        row = control_conn.execute(
            f"SELECT actor_id FROM harness_sessions WHERE session_id = {p}",
            (session_id,),
        ).fetchone()
    except _operational_error_types(control_conn):
        return None
    if row is None or row[0] is None:
        return None
    return str(row[0])


def _git_branch_and_commit(
    worktree_path: Path,
) -> tuple[Optional[str], Optional[str]]:
    if not worktree_path or not Path(worktree_path).exists():
        return None, None
    branch = _git_capture(worktree_path, ["branch", "--show-current"])
    commit = _git_capture(worktree_path, ["rev-parse", "HEAD"])
    return branch, commit


def _git_capture(worktree_path: Path, argv: List[str]) -> Optional[str]:
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


def _resolve_integration_target(profile: Mapping[str, Any]) -> str:
    """Default to ``main`` until profiles carry an explicit target."""
    target = profile.get("integration_target")
    if isinstance(target, str) and target.strip():
        return target.strip()
    return "main"


def _resolve_change_class(profile: Mapping[str, Any]) -> Optional[str]:
    """Map the operator-declared migration_strategy onto a change_class tag."""
    strategy = profile.get("migration_strategy")
    if isinstance(strategy, str) and strategy.strip():
        return strategy.strip()
    return None
