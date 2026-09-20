"""QA gate type definitions — GateTarget, GateResult, LatestCodeRef.

Extracted from qa_gates.py. These are pure data types with no DB or
subprocess dependencies, making them safe to import anywhere without
pulling in the heavier gate-check logic.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

# ``done`` asserts blocking QA is settled. Engine terminals abandon the item
# without that claim and without auto-waiving rows; the run still enforces
# run-owned QA at its own completion boundary.
QA_SETTLING_TERMINAL_STATUSES = frozenset({"done"})
QA_NONSETTLING_TERMINAL_STATUSES = frozenset({"cancelled", "stopped"})


def status_settles_blocking_qa(status: str) -> bool:
    """True when transitioning to *status* must settle blocking QA."""
    return status in QA_SETTLING_TERMINAL_STATUSES


def independent_item_obligation(row: Any) -> bool:
    """False for an admitted copy or a stage-acceptance row."""
    try:
        kind = str(row["qa_kind"] or "")
    except (KeyError, IndexError, TypeError):
        kind = ""
    from yoke_core.domain.deployment_qa_stage_prerequisites import (
        DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
    )

    if kind == DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND:
        return False
    try:
        key = row["plan_case_key"]
    except (KeyError, IndexError, TypeError):
        return True
    from yoke_core.domain.deployment_qa_admission_materialization import (
        admitted_source_requirement_id,
    )

    return admitted_source_requirement_id(key) is None


@dataclass
class GateTarget:
    """Parsed gate-check target: either an item ID or epic_id:task_num."""

    item_id: Optional[int] = None
    epic_id: Optional[int] = None
    task_num: Optional[int] = None

    @classmethod
    def parse(cls, raw: str) -> "GateTarget":
        """Resolve an operator gate target into typed internal ids."""
        from yoke_core.domain.yok_n_parser import parse_item_argument

        if ":" in raw:
            epic_ref, task_num = raw.split(":", 1)
            return cls(
                epic_id=parse_item_argument(epic_ref),
                task_num=int(task_num),
            )
        return cls(item_id=parse_item_argument(raw))

    def where_clause(self) -> Tuple[str, tuple]:
        """Return (SQL fragment, params) for this target's obligations.

        An item carries item-bound rows (``item_id``) and run-bound rows that
        name it as ``deployment_member_item_id``. Admitted copies settle a
        source rather than binding twice. Run-scoped rows with no member
        belong to the run's completion gate, so a member with nothing of its
        own to verify is not blocked by another member's cases.
        """
        if self.item_id is not None:
            return (
                "(item_id = %s OR deployment_member_item_id = %s)",
                (self.item_id, self.item_id),
            )
        return "epic_id = %s AND task_num = %s", (self.epic_id, self.task_num)

    def display_name(self, conn: Any) -> str:
        """Name this target the way an operator reads it.

        The reference comes from the connection the gate is reading, not
        an ambient one: a QA gate runs against a caller-supplied database,
        and resolving identity anywhere else would name a different item.
        """
        from yoke_core.domain.project_identity import render_item_ref

        if self.item_id is not None:
            return render_item_ref(conn, int(self.item_id))
        epic_ref = render_item_ref(conn, int(self.epic_id))
        return f"{epic_ref}/task {self.task_num}"


@dataclass
class GateResult:
    """Result of a gate check."""

    passed: bool
    errors: List[str] = field(default_factory=list)

    def emit_errors(self) -> None:
        for line in self.errors:
            print(line, file=sys.stderr)


@dataclass(frozen=True)
class LatestCodeRef:
    """Latest code identity for a target branch.

    ``accepted_shas`` carries every revision a run may legitimately have
    verified when more than one is authoritative — a merge produces a lane
    head, an integrated head, and a queue-entry head, and demanding one of
    them satisfy every requirement would call proven evidence stale. It is
    empty when a single ``sha`` is the whole answer.
    """

    branch: Optional[str] = None
    sha: Optional[str] = None
    timestamp: Optional[str] = None
    accepted_shas: tuple[str, ...] = ()
