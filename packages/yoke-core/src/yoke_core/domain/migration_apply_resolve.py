"""Project, capability, item, and module resolution for migration apply.

"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_mutation_profile import (
    MUTATION_INTENT_APPLY,
    STATE_DECLARED,
    STATE_NONE,
    validate as validate_profile,
)
from yoke_core.domain.migration_model_capability_validation import (
    CAPABILITY_TYPE as MIGRATION_MODEL_CAPABILITY_TYPE,
    validate as validate_capability,
)
from yoke_core.domain.migration_apply_contract import (
    MigrationApplyError,
    ProfileNotApplyError,
    _safe_parse_json_dict,
)
from yoke_core.domain.migration_history import (
    load_migration_module,
    resolve_migration_path,
)
from yoke_core.domain.project_identity import (
    format_item_ref,
    render_item_ref,
    resolve_project_id,
)
from yoke_core.domain.project_checkout_locations import (
    checkout_for_project,
    item_worktree_path,
)


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _operational_error_types(conn) -> tuple:
    return db_backend.operational_error_types(conn)


def _resolve_repo_path(conn: Any, project: str) -> Path:
    resolve_project_id(conn, project)
    checkout = checkout_for_project(conn, project)
    if checkout is None:
        raise MigrationApplyError(
            f"project '{project}' has no machine-local checkout mapping; "
            "cannot resolve migration module paths"
        )
    return checkout


def _resolve_capability_settings(
    conn: Any, project: str
) -> Dict[str, Any]:
    """Resolve the migration_model capability row for *project*.

    ``conn`` is the control-plane connection already owned by the caller.
    Reusing it keeps local-Postgres and relayed/server-side execution on the
    authority selected for that invocation. Opening a second ambient
    connection here can silently switch universes and cannot work inside an
    HTTPS request handler.
    """
    p = _placeholder(conn)
    try:
        project_id = resolve_project_id(conn, project)
    except LookupError as exc:
        raise MigrationApplyError(
            f"project '{project}' has no migration_model capability row"
        ) from exc
    except _operational_error_types(conn) as exc:
        raise MigrationApplyError(
            "project registry is unavailable on the supplied control-plane "
            f"connection for project '{project}': {exc}"
        ) from exc
    try:
        row = conn.execute(
            "SELECT COALESCE(settings, '{}') FROM project_capabilities "
            f"WHERE project_id={p} AND type={p}",
            (project_id, MIGRATION_MODEL_CAPABILITY_TYPE),
        ).fetchone()
    except _operational_error_types(conn) as exc:
        raise MigrationApplyError(
            "project_capabilities table is unavailable on the supplied "
            f"control-plane connection for project '{project}': {exc}"
        ) from exc
    if row is None:
        raise MigrationApplyError(
            f"project '{project}' has no migration_model capability row"
        )
    # Positional read is portable: the unaliased COALESCE column name differs
    # across SQLite and Postgres row objects, while row[0] is stable.
    raw = row[0]
    parsed = _safe_parse_json_dict(raw)
    if not parsed:
        raise MigrationApplyError(
            f"project '{project}' migration_model capability is empty or malformed"
        )
    return validate_capability(parsed)


def _resolve_item_worktree_path(conn, item_id: int) -> Optional[str]:
    """Return the machine-local item worktree path, or None when absent."""
    path = item_worktree_path(conn, item_id)
    return str(path) if path is not None else None


def default_worktree_path(
    conn, item_id: int, override: Optional[Path] = None,
) -> Path:
    """rehearse / live-apply worktree default: override > item.worktree > cwd."""
    if override is not None:
        return override
    resolved = _resolve_item_worktree_path(conn, item_id)
    return Path(resolved) if resolved else Path.cwd()


def _load_migration_module(modules_dir: Path, identifier: str) -> ModuleType:
    return load_migration_module(
        resolve_migration_path(modules_dir, identifier), identifier
    )


def _load_item(conn: Any, item_id: int) -> Dict[str, Any]:
    p = _placeholder(conn)
    row = conn.execute(
        "SELECT i.id, i.workflow_id, i.workflow_version_id, i.status, "
        "p.slug AS project, i.project_id, p.public_item_prefix, "
        "i.project_sequence, COALESCE(p.default_branch, 'main') AS integration_target, "
        "i.db_mutation_profile, "
        "i.db_compatibility_attestation "
        "FROM items i JOIN projects p ON p.id = i.project_id "
        f"WHERE i.id = {p}",
        (item_id,),
    ).fetchone()
    if row is None:
        raise MigrationApplyError(
            f"Item {render_item_ref(conn, item_id)} not found"
        )
    return dict(row)


def _resolve_profile_or_raise(item: Mapping[str, Any]) -> Dict[str, Any]:
    item_ref = format_item_ref(
        item.get("project"),
        item.get("public_item_prefix"),
        item.get("project_sequence"),
        item_id=item["id"],
    )
    raw = item.get("db_mutation_profile")
    parsed = _safe_parse_json_dict(raw)
    if not parsed or parsed.get("state") == STATE_NONE:
        raise ProfileNotApplyError(
            f"Item {item_ref} has no declared db_mutation_profile "
            "(state=none) — two-unit apply contract does not run"
        )
    profile = validate_profile(parsed)
    if profile["state"] != STATE_DECLARED:
        raise ProfileNotApplyError(
            f"Item {item_ref} profile state is {profile['state']!r}, "
            "expected 'declared'"
        )
    if profile["mutation_intent"] != MUTATION_INTENT_APPLY:
        raise ProfileNotApplyError(
            f"Item {item_ref} mutation_intent is "
            f"{profile['mutation_intent']!r}, expected 'apply'"
        )
    return profile


@dataclass(frozen=True)
class ResolvedMigrationInput:
    """The item values the shared runner core consumes."""

    item_id: int
    project: str
    project_id: int
    integration_target: str
    profile: Mapping[str, Any]
    attestation_raw: Any


def resolve_runner_input(
    control_conn: Any, *, item_id: Optional[int]
) -> ResolvedMigrationInput:
    """Load the item a governed apply runs against.

    Every governed apply is item-backed: its safety theorem comes from the
    item's declared profile and attestation. The itemless shape this once
    also accepted -- an operator-supplied manifest naming a subject -- existed
    to push migrations at installs from outside, which is no longer how a
    database reaches its code.
    """
    if item_id is None:
        raise MigrationApplyError("governed migration apply requires item_id")
    item = _load_item(control_conn, item_id)
    return ResolvedMigrationInput(
        item_id=item_id,
        project=str(item.get("project") or ""),
        project_id=int(item["project_id"]),
        integration_target=str(item.get("integration_target") or "main"),
        profile=_resolve_profile_or_raise(item),
        attestation_raw=item.get("db_compatibility_attestation"),
    )


def control_conn_db_path(conn: Any) -> Optional[str]:
    """Best-effort filesystem path for a sqlite3 connection (None for memory)."""
    # Postgres connections have no on-disk path; PRAGMA is SQLite-only.
    if db_backend.connection_is_postgres(conn):
        return None
    try:
        rows = conn.execute("PRAGMA database_list").fetchall()
    except db_backend.operational_error_types(conn):
        return None
    for row in rows:
        name = row["name"] if hasattr(row, "keys") else row[1]
        path = row["file"] if hasattr(row, "keys") else row[2]
        if name == "main":
            return path or None
    return None
