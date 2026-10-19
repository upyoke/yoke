"""Require an executable case or a real domain-owned discharge path."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def manual_credit_available(
    conn: Any, row: Mapping[str, Any], item_id: int | None
) -> bool:
    """The item QA gate can grade a verification row through manual review."""
    if conn is None or item_id is None or row.get("qa_phase") != "verification":
        return False
    # Existing unbound verification rows are graded by item QA too;
    # registered authoring validates a required binding before this check.
    if not row.get("workflow_transition_id"):
        return True
    from yoke_core.domain.qa_workflow_binding_validation import (
        validate_item_qa_transition,
    )

    try:
        validate_item_qa_transition(
            conn,
            item_id=int(item_id),
            transition_id=row.get("workflow_transition_id"),
            qa_phase="verification",
        )
    except (LookupError, ValueError):
        return False
    return True


def proof_refusal(
    row: Mapping[str, Any],
    *,
    subject: str,
    conn: Any = None,
    item_id: int | None = None,
) -> str:
    """Name the missing proof and recovery before any requirement is written."""
    if str(row.get("blocking_mode") or "blocking") != "blocking":
        return ""
    if str(row.get("method_id") or "").strip():
        return ""
    if manual_credit_available(conn, row, item_id):
        return ""
    if conn is not None and item_id is not None:
        from yoke_core.domain.project_identity import render_item_ref

        subject = f"{render_item_ref(conn, item_id)}, {subject}"
    criterion = (
        row.get("expected_outcome") or row.get("instructions") or row.get("qa_kind")
    )
    return (
        f"requirement_proof_required: {subject}, criterion {criterion!r}, "
        "has neither a runnable method nor a manual review credit path at this binding. Attach the plan case that proves this criterion "
        "with yoke qa item-plan attach, then yoke qa plan materialize; or add a "
        "registered --method-id with instructions, expected outcome and method config. "
        "Copying or transferring a requirement must retain a supported credit path."
    )
