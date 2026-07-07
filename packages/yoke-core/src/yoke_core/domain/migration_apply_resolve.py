"""Project, capability, item, and module resolution for migration apply.

Also owns the cross-worktree ``--module-path-override`` contract: a single
shared validator (:func:`resolve_module_override`) that both rehearse and
live-apply route through so the denied shapes are authored once and the
two units cannot disagree about what an override means.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Iterable, Mapping, Optional

from yoke_core.domain import db_backend, db_helpers
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
    ModuleContractError,
    ModuleOverrideError,
    ModuleResolutionError,
    ProfileNotApplyError,
    _safe_parse_json_dict,
)
from yoke_core.domain.project_identity import resolve_project_id
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

    Always reads ``project_capabilities`` from the canonical Yoke
    control-plane DB regardless of the connection passed in. The *conn*
    parameter is preserved for API stability and intentionally unused —
    validation-surface DBs do not carry the table, so the canonical DB
    is resolved through :func:`yoke_core.domain.db_helpers.resolve_db_path`.
    Raises :class:`MigrationApplyError` when the canonical DB or the
    table is unreachable.
    """
    del conn  # capability rows live on the canonical control plane only
    return _read_capability_from_canonical(project)


def _read_capability_from_canonical(project: str) -> Dict[str, Any]:
    try:
        canonical = db_helpers.connect()
    except FileNotFoundError as exc:
        raise MigrationApplyError(
            f"canonical Yoke control-plane DB unreachable for "
            f"project_capabilities lookup of '{project}': {exc} "
            "(resolved via yoke_core.domain.db_helpers.resolve_db_path)"
        ) from exc
    try:
        p = _placeholder(canonical)
        try:
            project_id = resolve_project_id(canonical, project)
        except LookupError as exc:
            raise MigrationApplyError(
                f"project '{project}' has no migration_model capability row"
            ) from exc
        try:
            row = canonical.execute(
                "SELECT COALESCE(settings, '{}') FROM project_capabilities "
                f"WHERE project_id={p} AND type={p}",
                (project_id, MIGRATION_MODEL_CAPABILITY_TYPE),
            ).fetchone()
        except _operational_error_types(canonical) as exc:
            raise MigrationApplyError(
                f"project_capabilities table unreachable on canonical "
                f"Yoke control-plane DB for project '{project}': {exc} "
                "(resolved via yoke_core.domain.db_helpers.resolve_db_path)"
            ) from exc
    finally:
        canonical.close()
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


def _load_migration_module_at_path(
    path: Path, identifier: str
) -> ModuleType:
    """Import a migration module from an explicit file path.

    Used by the default ``modules_dir / <identifier>.py`` loader and by
    the cross-worktree override path. Both must enforce the same
    ``apply(conn)`` contract.
    """
    if not path.is_file():
        raise ModuleResolutionError(
            f"migration module '{identifier}' not found at {path}"
        )
    spec_name = f"_governed_migration_{identifier}"
    spec = importlib.util.spec_from_file_location(spec_name, str(path))
    if spec is None or spec.loader is None:
        raise ModuleResolutionError(
            f"cannot construct import spec for {path}"
        )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 — surface as structured error
        raise ModuleResolutionError(
            f"failed to import migration module '{identifier}' from {path}: {exc}"
        ) from exc
    if not callable(getattr(module, "apply", None)):
        raise ModuleContractError(
            f"migration module '{identifier}' has no callable 'apply(conn)' surface"
        )
    return module


def _load_migration_module(modules_dir: Path, identifier: str) -> ModuleType:
    return _load_migration_module_at_path(
        modules_dir / f"{identifier}.py", identifier
    )


def _load_item(conn: Any, item_id: int) -> Dict[str, Any]:
    p = _placeholder(conn)
    row = conn.execute(
        "SELECT i.id, i.type, i.status, p.slug AS project, i.project_id, "
        "i.db_mutation_profile, "
        "i.db_compatibility_attestation "
        "FROM items i JOIN projects p ON p.id = i.project_id "
        f"WHERE i.id = {p}",
        (item_id,),
    ).fetchone()
    if row is None:
        raise MigrationApplyError(f"Item YOK-{item_id} not found")
    return dict(row)


def _resolve_profile_or_raise(item: Mapping[str, Any]) -> Dict[str, Any]:
    raw = item.get("db_mutation_profile")
    parsed = _safe_parse_json_dict(raw)
    if not parsed or parsed.get("state") == STATE_NONE:
        raise ProfileNotApplyError(
            f"Item YOK-{item['id']} has no declared db_mutation_profile "
            "(state=none) — two-unit apply contract does not run"
        )
    profile = validate_profile(parsed)
    if profile["state"] != STATE_DECLARED:
        raise ProfileNotApplyError(
            f"Item YOK-{item['id']} profile state is {profile['state']!r}, "
            "expected 'declared'"
        )
    if profile["mutation_intent"] != MUTATION_INTENT_APPLY:
        raise ProfileNotApplyError(
            f"Item YOK-{item['id']} mutation_intent is "
            f"{profile['mutation_intent']!r}, expected 'apply'. Retire flow "
            "is owned by yoke_core.domain.migration_retire_record."
        )
    return profile


# Cross-worktree module override contract — shared resolver + audit-description
# marker so rehearse/live-apply cannot disagree.


@dataclass(frozen=True)
class ModuleOverrideResolution:
    module_path: Path
    slug: str
    source_path: Path
    worktree_path: Path
    item_id: int


def resolve_module_override(
    *,
    requested_path: str,
    item_id: int,
    declared_modules: Iterable[str],
    worktree_path: Optional[str] = None,
) -> ModuleOverrideResolution:
    """Validate ``--module-path-override`` against the item's worktree.

    The caller passes ``worktree_path`` explicitly — typically computed
    from ``items.worktree`` joined with this machine's checkout mapping.
    Every denied shape — empty path, missing worktree_path, missing-on-
    disk path, non-file path, symlink escape, ``<slug>.py`` mismatch,
    undeclared slug — raises :class:`ModuleOverrideError`. There is no
    fall-back to main: refusal is structural so the rehearse / live-apply
    units cannot disagree about what an override means.
    """
    if not requested_path:
        raise ModuleOverrideError(
            "--module-path-override requires a non-empty path argument"
        )
    if not worktree_path:
        raise ModuleOverrideError(
            f"--module-path-override requires an active item worktree; "
            f"YOK-{item_id} has no worktree path (items.worktree is empty "
            "or this machine has no checkout mapping for the project)."
        )
    worktree_real = Path(worktree_path).expanduser().resolve()
    if not worktree_real.is_dir():
        raise ModuleOverrideError(
            f"--module-path-override active worktree path does not exist on "
            f"disk: {worktree_real}"
        )
    requested = Path(requested_path).expanduser()
    try:
        candidate_real = requested.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ModuleOverrideError(
            f"--module-path-override path does not exist: {requested}"
        ) from exc
    if not candidate_real.is_file():
        raise ModuleOverrideError(
            f"--module-path-override path is not a regular file: {candidate_real}"
        )
    try:
        candidate_real.relative_to(worktree_real)
    except ValueError as exc:
        raise ModuleOverrideError(
            f"--module-path-override path {candidate_real} is not under the "
            f"active item worktree {worktree_real} (symlink escape or "
            "out-of-worktree path)"
        ) from exc
    name = candidate_real.name
    if not name.endswith(".py"):
        raise ModuleOverrideError(
            f"--module-path-override file {candidate_real} must be named "
            f"<declared_slug>.py (got {name!r})"
        )
    slug = name[:-3]
    declared_set = {str(s) for s in declared_modules}
    if slug not in declared_set:
        raise ModuleOverrideError(
            f"--module-path-override slug {slug!r} (from filename {name!r}) "
            f"is not declared in db_mutation_profile.migration_modules; "
            f"declared modules: {sorted(declared_set)}"
        )
    return ModuleOverrideResolution(
        module_path=candidate_real, slug=slug, source_path=candidate_real,
        worktree_path=worktree_real, item_id=int(item_id),
    )


def load_module_with_override(
    *,
    modules_dir: Path,
    identifier: str,
    override: Optional[ModuleOverrideResolution],
) -> ModuleType:
    """Pick override path when its slug matches; otherwise default modules_dir."""
    if override is not None and override.slug == identifier:
        return _load_migration_module_at_path(override.module_path, identifier)
    return _load_migration_module(modules_dir, identifier)


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
