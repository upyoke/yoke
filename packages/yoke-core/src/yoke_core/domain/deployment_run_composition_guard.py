"""Durable immutability checks for frozen deployment-run composition."""

from __future__ import annotations

from typing import Any, Optional

#: Error code of a write refused because a newer run took this run over.
#: The successor owns the work, so the recovery is to watch it.
RUN_SUPERSEDED_CODE = "deployment_run_superseded"


def has_frozen_composition(conn: Any, run_id: str) -> bool:
    """The freeze marker remains authoritative across lifecycle status changes."""
    row = conn.execute(
        "SELECT composition_frozen_at IS NOT NULL FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    return bool(row and row[0])


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


def superseded_run_refusal(run_id: str, successor: str) -> str:
    return (
        f"Error: {RUN_SUPERSEDED_CODE}: deployment run '{run_id}' was taken over "
        f"by {successor}, which now owns its work; watch it with `yoke "
        f"deployment-runs get {successor}` instead of re-driving {run_id}"
    )


def terminal_run_refusal(
    conn: Any, run_id: str, status: str, *, advancing_to: str, action: str
) -> Optional[str]:
    """Refuse a write that would advance a cancelled run.

    Only ``cancelled`` is a deliberate, final stop: an operator (or the
    pipeline itself) means "this work is superseded, do not continue."
    ``failed`` is not the same guarantee -- reactivating a failed run back
    to ``executing`` is an established, tested retry-in-place recovery
    path (composition freeze is already idempotent for exactly this: see
    :func:`deployment_run_composition_freeze.freeze_run_composition`), and
    ``succeeded`` evidence keeps flowing in (post-deploy QA, bookkeeping)
    after the pipeline itself marks the run done. Rewriting the SAME
    already-cancelled value is a harmless no-op, not an attempted revival.
    A run cancelled by a takeover names its successor instead.
    """
    if status != "cancelled" or advancing_to == status:
        return None
    row = conn.execute(
        "SELECT superseded_by_run_id FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    if row and row[0]:
        return superseded_run_refusal(run_id, str(row[0]))
    return (
        f"Error: deployment run '{run_id}' is cancelled; a cancelled run "
        f"cannot {action}"
    )


__all__ = [
    "RUN_SUPERSEDED_CODE",
    "frozen_mutation_refusal",
    "has_frozen_composition",
    "mutable_field_refusal",
    "superseded_run_refusal",
    "terminal_run_refusal",
]
