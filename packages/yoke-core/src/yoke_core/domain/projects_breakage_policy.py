"""Reader for ``projects.breakage_policy`` with founder-build fallback.

``breakage_policy`` is a project-wide stance on how aggressively schema
and data cutovers can land in a single slice.

Allowed values::

    founder_cutover         = default; purge / hard cutover, expand-contract
                              needs justification
    compatibility_required  = old + new readers/writers may need to coexist;
                              hard cutover needs justification

The column is added and seeded by the
``project_model_simplification`` one-shot migration.  This reader
tolerates a pre-migration schema (column absent) so the joint gate can
admit the very ticket whose migration introduces the column — yoke's
own posture is hardcoded as the founder-cutover fallback.
"""

from __future__ import annotations

from typing import Any, Dict

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.schema_common import _column_exists as _schema_column_exists


POLICY_FOUNDER_CUTOVER = "founder_cutover"
POLICY_COMPATIBILITY_REQUIRED = "compatibility_required"
VALID_BREAKAGE_POLICIES = frozenset({
    POLICY_FOUNDER_CUTOVER,
    POLICY_COMPATIBILITY_REQUIRED,
})

# Pre-migration fallback when the column does not yet exist on the live
# DB.  After the migration runs, every project row carries an explicit
# value and this map is no longer consulted.
_PRE_MIGRATION_DEFAULTS: Dict[str, str] = {
    "yoke": POLICY_FOUNDER_CUTOVER,
}


class BreakagePolicyError(ValueError):
    """Raised when a stored ``breakage_policy`` value is not in the vocabulary."""


def _column_exists(conn: Any, table: str, column: str) -> bool:
    return _schema_column_exists(conn, table, column)


def resolve_breakage_policy(conn: Any, project: str) -> str:
    """Return the breakage policy for *project*.

    Reads ``projects.breakage_policy`` when the column exists and the
    project row has a non-null value.  Falls back to the pre-migration
    map when the column is absent or the row is missing — this lets the
    very ticket whose migration adds the column still pass its joint
    gate.

    Raises :class:`BreakagePolicyError` when the column exists but the
    stored value is outside :data:`VALID_BREAKAGE_POLICIES`.
    """
    if _column_exists(conn, "projects", "breakage_policy"):
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        ident = resolve_project(conn, project, required=False)
        numeric_project_id = ident.id if ident is not None else None
        row = None
        if numeric_project_id is not None:
            row = conn.execute(
                f"SELECT breakage_policy FROM projects WHERE id = {p}",
                (numeric_project_id,),
            ).fetchone()
        if row is not None:
            value = row["breakage_policy"] if hasattr(row, "keys") else row[0]
            if value:
                if value not in VALID_BREAKAGE_POLICIES:
                    raise BreakagePolicyError(
                        f"projects.breakage_policy for '{project}' is "
                        f"{value!r}; must be one of "
                        f"{sorted(VALID_BREAKAGE_POLICIES)}"
                    )
                return str(value)
    fallback = _PRE_MIGRATION_DEFAULTS.get(project, POLICY_COMPATIBILITY_REQUIRED)
    return fallback


__all__ = [
    "BreakagePolicyError",
    "POLICY_COMPATIBILITY_REQUIRED",
    "POLICY_FOUNDER_CUTOVER",
    "VALID_BREAKAGE_POLICIES",
    "resolve_breakage_policy",
]
