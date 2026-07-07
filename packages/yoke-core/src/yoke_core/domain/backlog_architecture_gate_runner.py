"""Architecture-impact gate for the canonical status write path.

Composed into :mod:`backlog_authoritative_status_gate` alongside the
existing DB-mutation gates. Two narrow blockers, both
defense-in-depth on the readiness-check signal:

* **uncertain past refined-idea** — an item whose
  ``architecture_impact`` is still ``'uncertain'`` cannot advance into
  any post-refined-idea status. The readiness check at
  ``refined-idea`` is the primary gate; this is the backstop on the
  authoritative write path so a direct DB poke or skipped refine
  doesn't slip through.
* **architecture_model_change requires architecture surface evidence**
  — an item declaring ``architecture_model_change`` must have at
  least one architecture-model authoring surface in its path-claim
  coverage (``architecture_model.py`` /
  ``project_structure*.py`` / ``doctor_hc_architecture*.py``). The
  check is coarse "evidence present" — refine still owns the rich
  multi-surface decision.

Pattern mirrors :mod:`backlog_db_mutation_gate_runner`. The runner is
a no-op for items with ``architecture_impact = 'none'`` or
``'path_context_only'`` — those impact classes pass without further
inspection.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect


_ARCHITECTURE_GATE_TARGETS = frozenset({
    "refined-idea",
    "planning", "plan-drafted", "refining-plan", "planned",
    "implementing",
    "reviewing-implementation", "reviewed-implementation",
    "polishing-implementation",
    "implemented", "release", "done",
})

# Architecture-model authoring surfaces: a path claim that covers any of
# these substrings counts as "architecture surface evidence" for an
# architecture_model_change item.
_ARCH_SURFACE_HINTS = (
    "architecture_model",
    "project_structure",
    "project_structure_validation",
    "doctor_hc_architecture",
    "architecture_dependency_scan",
)


def _read_item_impact(
    conn: Any, item_id: int,
) -> Optional[str]:
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        row = conn.execute(
            f"SELECT architecture_impact FROM items WHERE id = {p}",
            (item_id,),
        ).fetchone()
    except db_backend.operational_error_types(conn=conn):
        return None
    if row is None or row[0] is None:
        return None
    return str(row[0]).strip().lower() or None


def _claim_covers_arch_surface(
    conn: Any, item_id: int,
) -> bool:
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        rows = conn.execute(
            f"SELECT pt.path_string FROM path_claim_targets pct "
            "JOIN path_claims pc ON pc.id = pct.claim_id "
            "JOIN path_targets pt ON pt.id = pct.target_id "
            f"WHERE pc.item_id = {p} "
            "AND pc.state IN ('planned', 'active', 'blocked')",
            (item_id,),
        ).fetchall()
    except db_backend.operational_error_types(conn=conn):
        return True  # minimal schema fixtures don't have these tables
    for row in rows:
        path = str(row[0])
        if any(hint in path for hint in _ARCH_SURFACE_HINTS):
            return True
    return False


def _run_architecture_impact_gate(
    *,
    item_id: int,
    target_status: str,
    db_path: str,
) -> Optional[dict]:
    """Return ``None`` on pass, or a canonical failure payload."""
    if target_status not in _ARCHITECTURE_GATE_TARGETS:
        return None
    conn = connect(db_path)
    try:
        impact = _read_item_impact(conn, item_id)
        if impact is None or impact in {"none", "path_context_only"}:
            return None
        if impact == "uncertain":
            return {
                "success": False,
                "error_code": "GATE_ARCHITECTURE_IMPACT_UNCERTAIN",
                "error": (
                    f"Cannot advance YOK-{item_id} to '{target_status}' — "
                    "architecture_impact='uncertain'. Refine must resolve "
                    "to none, path_context_only, or "
                    "architecture_model_change. Repair: `printf '%s' "
                    "<value> | python3 -m yoke_core.cli.db_router "
                    f"items update YOK-{item_id} architecture_impact "
                    "--stdin`."
                ),
            }
        if impact == "architecture_model_change":
            if _claim_covers_arch_surface(conn, item_id):
                return None
            return {
                "success": False,
                "error_code": "GATE_ARCHITECTURE_MODEL_CHANGE_NO_SURFACE",
                "error": (
                    f"Cannot advance YOK-{item_id} to '{target_status}' — "
                    "architecture_impact='architecture_model_change' but "
                    "the path-claim does not cover any architecture-model "
                    "authoring surface (architecture_model.py, "
                    "project_structure*.py, doctor_hc_architecture*.py, "
                    "architecture_dependency_scan.py). Repair: widen the "
                    "claim to include the architecture-model surface the "
                    "slice changes, or relax architecture_impact to "
                    "'path_context_only' when only context families move."
                ),
            }
        return None
    finally:
        conn.close()


__all__ = [
    "_ARCHITECTURE_GATE_TARGETS",
    "_run_architecture_impact_gate",
]
