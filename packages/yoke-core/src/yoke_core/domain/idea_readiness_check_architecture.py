"""Readiness check: architecture_impact must be resolved before
refined-idea.

Owns the ``ARCHITECTURE_IMPACT_UNCERTAIN`` issue code. Implementation-
bearing items that still carry ``architecture_impact = 'uncertain'`` at
refine time fail the readiness check and are routed back to refine /
Architect resolution. ``none``, ``path_context_only``, and
``architecture_model_change`` all pass.

This module is a sibling of
:mod:`yoke_core.domain.idea_readiness_check` so the main module stays
under the 350-line file cap; the parent composes this check into
``run_all_checks``.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING, List

from . import db_backend
from yoke_core.domain.architecture_impact import (
    IMPACT_UNCERTAIN,
    is_readiness_resolved,
)

if TYPE_CHECKING:
    from yoke_core.domain.idea_readiness_check import Issue


def _read_architecture_impact(
    conn: Any, item_id: int,
) -> str:
    """Return the item's stored architecture_impact value or
    :data:`yoke_core.domain.architecture_impact.NEGATIVE_DEFAULT`
    when the column is missing or NULL."""
    try:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT architecture_impact FROM items WHERE id = {p}",
            (item_id,),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        return "none"
    if row is None or row[0] is None or str(row[0]).strip() == "":
        return "none"
    return str(row[0]).strip().lower()


def verify_architecture_impact_resolved(
    conn: Any, item_id: int,
) -> List["Issue"]:
    """Emit ``ARCHITECTURE_IMPACT_UNCERTAIN`` when the item's
    ``architecture_impact`` is still ``'uncertain'``.

    Pre-existing rows (missing column / NULL value) read as
    :data:`architecture_impact.NEGATIVE_DEFAULT` = ``'none'``, which
    passes the check without operator action.
    """
    from yoke_core.domain.idea_readiness_check import Issue

    value = _read_architecture_impact(conn, item_id)
    if is_readiness_resolved(value):
        return []
    if value != IMPACT_UNCERTAIN:
        return []
    return [Issue(
        code="ARCHITECTURE_IMPACT_UNCERTAIN",
        message=(
            "architecture_impact='uncertain' — refine must resolve "
            "this to none, path_context_only, or "
            "architecture_model_change before refined-idea."
        ),
        remediation=(
            "Decide whether this item touches architecture surfaces "
            "(dependency shape, path classification, cross-cutting "
            "entrypoints, or the architecture_model payload). Set the "
            "resolved value with `printf '%s' <value> | python3 -m "
            "yoke_core.cli.db_router items update YOK-N "
            "architecture_impact --stdin`."
        ),
        context={"current_value": value},
    )]


__all__ = ["verify_architecture_impact_resolved"]
