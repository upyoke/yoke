"""The verdict a re-drive gives a run whose composition is already frozen.

Freezing validated the run's carried work, custody, dependencies and member
flows, and none of them can change afterwards. Repeating that validation on
every re-drive walked the same sources and custody again for a run already
executing. What can still change is judged here: a member that left delivery
readiness since the freeze, and a run left with no member its item-scoped QA
can prove. The verdict has the shape and wording of
``cmd_validate_composition``.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.deployment_run_item_qa_membership import (
    item_qa_membership_verdict,
)
from yoke_core.domain.deployment_run_reopened_members import (
    frozen_member_readiness,
)


def frozen_composition_verdict(conn: Any, run_id: str) -> tuple[bool, str]:
    """Return ``(ok, message)`` for a re-drive of frozen *run_id*."""
    refused, set_aside = frozen_member_readiness(conn, run_id)
    errors = (
        ["Items not delivery-ready for their pinned workflow: " + ", ".join(refused)]
        if refused
        else []
    )
    item_qa, no_member = item_qa_membership_verdict(conn, run_id)
    errors.extend([item_qa] if item_qa else [])
    if errors:
        text = "\n".join(errors + ([set_aside] if set_aside else []))
        return False, f"FAIL: Composition validation failed:\n{text}"
    notes = [note for note in (set_aside, no_member) if note]
    return True, ("OK; " + "; ".join(notes)) if notes else "OK"


__all__ = ["frozen_composition_verdict"]
