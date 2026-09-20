"""The one way a blocking QA obligation is settled without fresh evidence.

Two boundaries ask this question about the same rows. A deployment stage's
acceptance check asks it per case, to tell "nothing left to execute" from
"nothing was executed". The run-completing stage asks it across the whole
run, to tell a release that may finish from one still owing an answer.

They must agree, because they read the same requirements. When the final
stage honoured only ``waived_at``, a requirement a passing replacement had
already superseded — settled as far as the stage that examined it was
concerned — came back as "no passing run" at the end of the release, and the
only way past it was to waive a row nobody needed to waive.

Waiver and supersession settle an obligation for different reasons and stay
distinct records: one is an operator override, the other is a replacement
requirement that carries the obligation now. Neither leaves evidence for the
original row to show, which is the whole of what these boundaries ask.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


#: A ``qa_requirements`` row is settled when either discharge record is set.
#: Rendered as SQL for the readers that filter in the query, and applied to a
#: row for the readers that already hold one — one rule, two shapes.
SETTLED_OBLIGATION_SQL = (
    "({alias}waived_at IS NOT NULL "
    "OR {alias}superseded_by_requirement_id IS NOT NULL "
    "OR {alias}retracted_at IS NOT NULL)"
)


def settled_obligation_sql(alias: str = "") -> str:
    """Render the settled predicate for one ``qa_requirements`` alias."""
    return SETTLED_OBLIGATION_SQL.format(alias=f"{alias}." if alias else "")


def obligation_settled(row: Mapping[str, Any]) -> bool:
    """Whether this requirement row is already settled without evidence."""
    return bool(row.get("waived_at")) or bool(
        row.get("superseded_by_requirement_id")
    ) or bool(row.get("retracted_at"))


__all__ = [
    "SETTLED_OBLIGATION_SQL",
    "obligation_settled",
    "settled_obligation_sql",
]
