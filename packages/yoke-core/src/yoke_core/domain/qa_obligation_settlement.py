"""Effective QA obligations: discharged rows and replaced predecessors are history.

A valid declaration immediately transfers grading to its successor, including
when that successor is pending or failing. Passing supersession remains a
separate durable discharge record. Writers validate scope and acyclicity
before these read predicates can exclude a predecessor.
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
    "OR {alias}replacement_requirement_id IS NOT NULL "
    "OR {alias}retracted_at IS NOT NULL)"
)
_SETTLED_WITHOUT_RETRACT_SQL = (
    "({alias}waived_at IS NOT NULL "
    "OR {alias}replacement_requirement_id IS NOT NULL "
    "OR {alias}superseded_by_requirement_id IS NOT NULL)"
)


def settled_obligation_sql(conn: Any, alias: str = "") -> str:
    """Render the settled predicate for one ``qa_requirements`` alias."""
    prefix = f"{alias}." if alias else ""
    template = SETTLED_OBLIGATION_SQL
    if not _column_exists(conn, "qa_requirements", "retracted_at"):
        template = _SETTLED_WITHOUT_RETRACT_SQL
    rendered = template.format(alias=prefix)
    if not _column_exists(conn, "qa_requirements", "replacement_requirement_id"):
        rendered = rendered.replace(
            f"OR {prefix}replacement_requirement_id IS NOT NULL ", ""
        )
    from yoke_core.domain.qa_simulation_triage import triage_discharge_sql

    return f"({rendered} OR {triage_discharge_sql(conn, alias)})"


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


def item_supersession_open_sql(conn: Any, alias: str = "") -> str:
    """Rows not settled by an item-bound supersession.

    An item-bound row is superseded only by a passing case bound to the same
    item, transition and phase, which the same gate grades on its own
    evidence, so the link settles it outright. A run-bound member row keeps
    its stricter ``done`` validation (stage acceptance and a same-scope
    passing replacement), so this predicate never drops one. A table without
    the column has superseded nothing.
    """
    return unanswered_attempt_sql(conn, alias)


def unanswered_attempt_sql(conn: Any, alias: str = "") -> str:
    """Rows an execution roster still owes an attempt.

    A superseded row is answered, and a row with a declared replacement has
    handed its attempt to that corrected case; re-running either would only
    re-judge history. A table without a column has neither.
    """
    prefix = f"{alias}." if alias else ""
    clauses = [
        f"{prefix}{column} IS NULL"
        for column in ("superseded_by_requirement_id", "replacement_requirement_id")
        if _column_exists(conn, "qa_requirements", column)
    ]
    from yoke_core.domain.qa_simulation_triage import triage_discharge_sql

    clauses.append(f"NOT {triage_discharge_sql(conn, alias)}")
    return " AND ".join(clauses)


def item_supersession_settled(row: Mapping[str, Any]) -> bool:
    """Row form of :func:`item_supersession_open_sql`, negated."""
    return not row.get("replacement_graph_error") and (
        bool(row.get("superseded_by_requirement_id"))
        or bool(row.get("replacement_requirement_id"))
        or bool(row.get("triage_discharge"))
    )


def obligation_settled(row: Mapping[str, Any]) -> bool:
    """Whether this requirement row is already settled without evidence."""
    return not row.get("replacement_graph_error") and (
        bool(row.get("waived_at"))
        or bool(row.get("superseded_by_requirement_id"))
        or bool(row.get("retracted_at"))
        or bool(row.get("replacement_requirement_id"))
        or bool(row.get("triage_discharge"))
    )


def effective_requirement(conn: Any, requirement_id: int) -> dict[str, Any]:
    """Follow the durable correction graph to its final same-scope obligation."""
    from yoke_core.domain.db_helpers import query_one
    from yoke_core.domain.qa_plan_execution_store import marker
    from yoke_core.domain.qa_replacement_scope_guard import (
        LINK_REPAIR,
        link_mismatches,
    )

    seen: set[int] = set()
    previous = None
    while True:
        if requirement_id in seen:
            raise ValueError(
                "replacement_graph_invalid: correction cycle; restore an acyclic same-scope chain through registered correction surfaces"
            )
        seen.add(requirement_id)
        stored = query_one(
            conn,
            f"SELECT * FROM qa_requirements WHERE id={marker(conn)}",
            (requirement_id,),
        )
        if stored is None:
            raise ValueError(
                "replacement_graph_invalid: missing successor; restore the named requirement through the control-plane operator"
            )
        row = dict(stored)
        mismatches = link_mismatches(previous, row) if previous is not None else []
        if mismatches:
            raise ValueError(
                f"replacement_graph_invalid: requirement #{previous['id']} links to "
                f"#{row['id']}, which no longer answers for the same obligation "
                f"({'; '.join(mismatches)}); {LINK_REPAIR}"
            )
        edges = {
            int(row[key])
            for key in ("replacement_requirement_id", "superseded_by_requirement_id")
            if row.get(key)
        }
        if len(edges) > 1:
            raise ValueError(
                "replacement_graph_invalid: conflicting successor links; reconcile their durable correction audit with the control-plane operator"
            )
        if not edges:
            return row
        previous, requirement_id = row, edges.pop()


def effective_obligations(
    conn: Any, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Normalize selected obligations while retaining named graph refusals."""
    selected = {}
    for row in rows:
        try:
            effective = effective_requirement(conn, int(row["id"]))
        except ValueError as exc:
            if not str(exc).startswith("replacement_graph_invalid:"):
                raise
            effective = dict(row, replacement_graph_error=str(exc))
        selected[int(effective["id"])] = effective
    return list(selected.values())


__all__ = [
    "SETTLED_OBLIGATION_SQL",
    "effective_requirement",
    "item_supersession_open_sql",
    "item_supersession_settled",
    "unanswered_attempt_sql",
    "obligation_settled",
    "requirement_retracted_at_select",
    "settled_obligation_sql",
    "unretracted_requirement_sql",
]
