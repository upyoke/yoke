"""Durable immutability checks for frozen deployment-run composition."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.schema_common import _column_exists


def has_frozen_composition(conn: Any, run_id: str) -> bool:
    """Return whether the additive composition-freeze marker is populated.

    An unconverged legacy schema has no marker and retains its status-only
    mutation contract. Once the additive column exists, the marker remains
    authoritative even if legacy tooling writes an earlier lifecycle status.
    """
    if not _column_exists(conn, "deployment_runs", "composition_frozen_at"):
        return False
    row = conn.execute(
        "SELECT COALESCE(composition_frozen_at, '') FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    return bool(row and str(row[0] or ""))


def frozen_mutation_refusal(run_id: str, subject: str) -> str:
    return (
        f"Error: {subject} is immutable because deployment run '{run_id}' "
        "has a frozen composition; cancel it and prepare a new run"
    )


def mutable_field_refusal(
    conn: Any, run_id: str, field: str, status: str
) -> Optional[str]:
    """Return why a candidate field cannot be changed, if it can be."""
    if has_frozen_composition(conn, run_id):
        return frozen_mutation_refusal(run_id, field)
    if status != "created":
        return (
            f"Error: {field} is mutable only while deployment run "
            f"'{run_id}' has status='created'"
        )
    return None


__all__ = [
    "frozen_mutation_refusal",
    "has_frozen_composition",
    "mutable_field_refusal",
]
