"""Linked open work whose document has no live steering seat."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.item_ref_render import render_item_refs
from yoke_core.domain.project_identity import resolve_project_slug
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.steering_scope_coverage import covering_seat, live_steering_claims
from yoke_core.domain.steering_scope_membership import item_coverage_target


@dataclass(frozen=True)
class UnattendedLinkedItem:
    item_id: int
    public_ref: str
    document_project: str
    document: str

    @property
    def finding(self) -> str:
        return (
            f"{self.public_ref}: unattended — linked to {self.document} in "
            f"{self.document_project}, no seat holds it; acquire with "
            f"`yoke claims steering acquire --project {self.document_project} "
            f"--doc {self.document}`"
        )


def unattended_linked_items(
    conn: Any, held_project_ids: Iterable[int]
) -> tuple[UnattendedLinkedItem, ...]:
    """Find linked work visible to these projects but covered by no seat."""
    projects = tuple(dict.fromkeys(int(value) for value in held_project_ids))
    if (
        not projects
        or not _table_exists(conn, "item_strategy_docs")
        or not _table_exists(conn, "workflow_versions")
    ):
        return ()
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    slots = ",".join(marker for _ in projects)
    rows = conn.execute(
        "SELECT i.id, i.project_id AS item_project_id, "
        "l.project_id AS document_project_id, l.strategy_doc_slug "
        "FROM items i JOIN item_strategy_docs l ON l.item_id = i.id "
        f"WHERE (i.project_id IN ({slots}) OR l.project_id IN ({slots})) "
        "AND i.status NOT IN ('done', 'cancelled', 'stopped') "
        "ORDER BY i.id",
        (*projects, *projects),
    ).fetchall()
    claims = live_steering_claims(conn)
    records = [dict(row) for row in rows]
    refs = render_item_refs(conn, [int(row["id"]) for row in records])
    names: dict[int, str] = {}
    findings = []
    for row in records:
        item_id = int(row["id"])
        target = item_coverage_target(
            conn,
            project_id=int(row["item_project_id"]),
            item_id=item_id,
            links={
                item_id: (
                    int(row["document_project_id"]),
                    str(row["strategy_doc_slug"]),
                )
            },
        )
        if covering_seat(conn, target, claims=claims) is not None:
            continue
        owner = int(row["document_project_id"])
        if owner not in names:
            names[owner] = resolve_project_slug(conn, owner)
        findings.append(
            UnattendedLinkedItem(
                item_id=item_id,
                public_ref=refs.get(item_id, str(item_id)),
                document_project=names[owner],
                document=str(row["strategy_doc_slug"]),
            )
        )
    return tuple(findings)


__all__ = ["UnattendedLinkedItem", "unattended_linked_items"]
