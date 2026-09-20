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

from yoke_core.domain.schema_common import _column_exists


#: A ``qa_requirements`` row is settled when a discharge record is set.
#: Rendered as SQL for the readers that filter in the query, and applied to a
#: row for the readers that already hold one — one rule, two shapes.
SETTLED_OBLIGATION_SQL = (
    "({alias}waived_at IS NOT NULL "
    "OR {alias}superseded_by_requirement_id IS NOT NULL "
    "OR {alias}retracted_at IS NOT NULL)"
)
_SETTLED_WITHOUT_RETRACT_SQL = (
    "({alias}waived_at IS NOT NULL "
    "OR {alias}superseded_by_requirement_id IS NOT NULL)"
)


def settled_obligation_sql(conn: Any, alias: str = "") -> str:
    """Render the settled predicate for one ``qa_requirements`` alias."""
    prefix = f"{alias}." if alias else ""
    template = SETTLED_OBLIGATION_SQL
    if not _column_exists(conn, "qa_requirements", "retracted_at"):
        template = _SETTLED_WITHOUT_RETRACT_SQL
    return template.format(alias=prefix)


def unretracted_requirement_sql(conn: Any, alias: str = "") -> str:
    """Live requirements only. Missing ``retracted_at`` means every row is live."""
    prefix = f"{alias}." if alias else ""
    if not _column_exists(conn, "qa_requirements", "retracted_at"):
        return "TRUE"
    return f"{prefix}retracted_at IS NULL"


def requirement_retracted_at_select(conn: Any, alias: str = "") -> str:
    """Select ``retracted_at``, or NULL when the column has not landed yet."""
    prefix = f"{alias}." if alias else ""
    if _column_exists(conn, "qa_requirements", "retracted_at"):
        return f"{prefix}retracted_at"
    return "NULL AS retracted_at"


def obligation_settled(row: Mapping[str, Any]) -> bool:
    """Whether this requirement row is already settled without evidence."""
    return bool(row.get("waived_at")) or bool(
        row.get("superseded_by_requirement_id")
    ) or bool(row.get("retracted_at"))


__all__ = [
    "SETTLED_OBLIGATION_SQL",
    "obligation_settled",
    "requirement_retracted_at_select",
    "settled_obligation_sql",
    "unretracted_requirement_sql",
]
