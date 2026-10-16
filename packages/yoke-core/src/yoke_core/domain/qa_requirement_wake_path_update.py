"""Validate an in-place ``wake_path`` or ``wake_evidence`` requirement write.

The two fields travel together: a ``manual`` case needs evidence naming what
must exist before steering wakes its owner. A requirement write carries one
field at a time, so the order is evidence first, then the path; clearing goes
the other way. Each refusal names the write that comes first.

Neither field changes what a case does when it runs, so a write reaches the
named row only, including a deployment run's admitted copy. It never rewrites
other rows or the plan behind them.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.qa_case_wake_path import (
    MANUAL,
    WAKE_EVIDENCE_REQUIRED,
    WakePathError,
    stored_wake_path,
    validated_wake_evidence,
    validated_wake_path,
)
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_requirement_pass_currency import _marker

WAKE_FIELDS = ("wake_path", "wake_evidence")


def prepare_wake_field(
    conn: Any, req_id: int, field: str, value: Any
) -> tuple[Optional[str], str]:
    """Return the stored value, or ``(None, refusal)`` naming the first write."""
    subject = f"QA requirement {int(req_id)}"
    row = query_one(
        conn,
        "SELECT wake_path, wake_evidence FROM qa_requirements "
        f"WHERE id = {_marker(conn)}",
        (int(req_id),),
    )
    current_path = stored_wake_path(row[0] if row else None)
    current_evidence = str((row[1] if row else "") or "").strip()
    try:
        if field == "wake_path":
            path = validated_wake_path(value, subject=subject)
            if path == MANUAL and not current_evidence:
                return None, (
                    f"{subject}: {WAKE_EVIDENCE_REQUIRED}: wake_path 'manual' "
                    "needs wake_evidence on the row first. Set it with `yoke qa "
                    f"requirement update --requirement-id {int(req_id)} --field "
                    "wake_evidence --value '<one line naming the real-traffic "
                    "evidence a registered read can confirm>'`, then set "
                    "wake_path again."
                )
            return path, ""
        evidence = validated_wake_evidence(value, subject=subject)
    except WakePathError as exc:
        return None, str(exc)
    if evidence is None and current_path == MANUAL:
        return None, (
            f"{subject}: {WAKE_EVIDENCE_REQUIRED}: the row's wake_path is "
            "'manual', which needs wake_evidence. Set wake_path to 'automatic' "
            f"first (`yoke qa requirement update --requirement-id {int(req_id)} "
            "--field wake_path --value automatic`), then clear wake_evidence."
        )
    return evidence, ""


__all__ = ["WAKE_FIELDS", "prepare_wake_field"]
