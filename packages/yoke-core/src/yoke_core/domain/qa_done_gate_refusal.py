"""How the done gate explains the blocking requirements still holding an item.

Split out of :mod:`qa_gates` to stay under the authored file line budget. The
gate decides which rows still block; this renders why each one does and what
clears it, which differs by phase: a row that has never run is executed, while
a post_deploy row may already have a passing run recorded against a candidate
this delivery is not about, and is cleared by delivery or an authorized waiver
instead.
"""

from __future__ import annotations

from typing import Any, Sequence

from yoke_core.domain.deployment_qa_source_obligation import POST_DEPLOY_RECOVERY
from yoke_core.domain.qa_review_requests import requirement_awaits_human_review

POST_DEPLOY_PHASE = "post_deploy"


def _phase(row: Any) -> str:
    return str(row["qa_phase"] or "")


def done_gate_refusal_errors(
    conn: Any, rows: Sequence[Any], *, name: str
) -> list[str]:
    """The operator-facing refusal for rows that still hold ``done``."""
    errors = [
        f"Error: Cannot transition {name} to 'done' -- {len(rows)} blocking "
        "QA requirement(s) unsatisfied.",
        "  All blocking requirements must have a passing run or be waived.",
        "  Satisfy each requirement or use the registered waiver "
        "surface with explicit authorization.",
    ]
    for row in rows:
        waiting = requirement_awaits_human_review(conn, int(row["id"]))
        if waiting:
            errors.extend([f"  - {waiting.detail}", f"    {waiting.recovery}"])
            continue
        reason = (
            "not accepted on the completion run"
            if _phase(row) == POST_DEPLOY_PHASE
            else "no passing run"
        )
        errors.append(
            f"  - Requirement #{row['id']} ({row['qa_kind']}, "
            f"phase={row['qa_phase']}): {reason}"
        )
    if any(_phase(row) == POST_DEPLOY_PHASE for row in rows):
        errors.append(f"  {POST_DEPLOY_RECOVERY}")
    return errors


__all__ = ["done_gate_refusal_errors"]
