"""Keep stored QA replacement links answering for one obligation.

A replacement or supersession link is valid only while both rows bind the
same obligation scope (:func:`same_scope`) and the successor is a blocking
case the gate grades. Every link writer checks that when it writes the link,
but a later field change on either row, or a later change to the scope rules
themselves, can break a link that was valid when written. The done gate then
refuses with ``replacement_graph_invalid``.

:func:`link_mismatches` is the one rule: the gate's graph walk and the
writers that can change a linked row's scope both read it, so a change to the
scope rules reaches all of them at once. Links held by a waived or retracted
row no longer carry an obligation and are not checked.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_obligation_settlement import unretracted_requirement_sql

LINK_COLUMNS = ("replacement_requirement_id", "superseded_by_requirement_id")
LINKED_SCOPE_CHANGE_CODE = "replacement_link_scope_changed"
#: Updatable requirement fields that :func:`link_mismatches` reads.
LINK_SCOPE_FIELDS = frozenset(
    {"target_env", "qa_phase", "workflow_transition_id", "blocking_mode"}
)
LINK_REPAIR = (
    "repair each listed predecessor with `yoke qa requirement supersede "
    "--requirement-id PRED --superseded-by-requirement-id PASSING_SAME_SCOPE_CASE "
    "--reconcile --source operator --rationale TEXT`, or waive it with "
    "`yoke qa requirement waive --requirement-id PRED --source operator "
    "--rationale TEXT`"
)


def link_mismatches(
    predecessor: Mapping[str, Any], successor: Mapping[str, Any]
) -> list[str]:
    """Every way *successor* fails to answer for *predecessor*'s obligation."""
    from yoke_core.domain.qa_requirement_supersession import same_scope

    mismatches = same_scope(dict(predecessor), dict(successor))
    if str(successor.get("blocking_mode") or "") != "blocking":
        mismatches.append(
            f"successor blocking mode is {successor.get('blocking_mode')!r}, not 'blocking'"
        )
    return mismatches


def _live_link_rows(conn: Any, where: str, params: Sequence[Any]) -> list[dict]:
    return [
        dict(row)
        for row in query_rows(
            conn,
            "SELECT * FROM qa_requirements r WHERE r.waived_at IS NULL "
            f"AND {unretracted_requirement_sql(conn, 'r')} AND ({where}) ORDER BY r.id",
            tuple(params),
        )
    ]


def _rows_by_id(conn: Any, ids: set[int]) -> dict[int, dict]:
    if not ids:
        return {}
    marks = ",".join(["%s"] * len(ids))
    rows = query_rows(
        conn, f"SELECT * FROM qa_requirements WHERE id IN ({marks})", tuple(ids)
    )
    return {int(row["id"]): dict(row) for row in rows}


def _broken(predecessors: list[dict], rows: dict[int, dict]) -> list[str]:
    findings: list[str] = []
    for pred in predecessors:
        for column in LINK_COLUMNS:
            target = pred.get(column)
            if not target:
                continue
            successor = rows.get(int(target))
            problems = (
                ["successor row is missing"]
                if successor is None
                else link_mismatches(pred, successor)
            )
            if problems:
                findings.append(
                    f"requirement #{pred['id']} {column} -> #{int(target)}: "
                    + "; ".join(problems)
                )
    return findings


def broken_links_touching(conn: Any, requirement_ids: Sequence[int]) -> list[str]:
    """Broken links into or out of *requirement_ids*, read on *conn* now."""
    ids = sorted({int(value) for value in requirement_ids})
    if not ids:
        return []
    marks = ",".join(["%s"] * len(ids))
    predecessors = _live_link_rows(
        conn,
        f"r.id IN ({marks}) OR "
        + " OR ".join(f"r.{column} IN ({marks})" for column in LINK_COLUMNS),
        ids * (1 + len(LINK_COLUMNS)),
    )
    targets = {int(p[c]) for p in predecessors for c in LINK_COLUMNS if p.get(c)}
    return _broken(predecessors, _rows_by_id(conn, targets))


def linked_scope_refusal(
    conn: Any, requirement_ids: Sequence[int], *, change: str
) -> str:
    """Name the links *change* would break, or return ``""`` when none break.

    Call after the write and before commit, so the check reads the rows as
    they would be stored; on a refusal the caller rolls the write back.
    """
    findings = broken_links_touching(conn, requirement_ids)
    if not findings:
        return ""
    return (
        f"{LINKED_SCOPE_CHANGE_CODE}: {change} would break the replacement "
        "link(s) below, so nothing was written:\n  "
        + "\n  ".join(findings)
        + "\nKeep the linked rows in one obligation scope: correct the case "
        "through a fresh same-scope replacement instead, or first " + LINK_REPAIR + "."
    )


__all__ = [
    "LINKED_SCOPE_CHANGE_CODE",
    "LINK_SCOPE_FIELDS",
    "LINK_COLUMNS",
    "LINK_REPAIR",
    "broken_links_touching",
    "link_mismatches",
    "linked_scope_refusal",
]
