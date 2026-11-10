"""Which steering seat sees one operator question.

Questions follow the coverage rule items and steering mail already follow
(:mod:`yoke_core.domain.steering_scope_coverage`). A question's work is the
item named in its ``subject_context``; failing that, the item its asking
session holds a work claim on; failing that, its project. The live seat
covering that work sees the question, so a document seat sees questions
about its member items in any project, and a project seat does not see
what a live document seat covers.

A seat always sees the questions it filed. Another hand-started session
(``launch_origin = 'operator'``) has its operator in its own chat, so its
questions never show. Work no live seat covers waits like parked mail: the
project seat for the owning project sees it marked unattended, and it moves
to the document seat once that seat is taken. A question with no project
shows only when it is addressed to the viewer's actor.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.steering_scope_coverage import (
    DOCUMENT_KEY,
    DOCUMENT_PROJECT_KEY,
    PROJECT_KEY,
    covering_seat,
    live_steering_claims,
)
from yoke_core.domain.steering_scope_membership import (
    item_coverage_target,
    item_document_links,
)
from yoke_core.domain.work_claim_targets import TARGET_KIND_ITEM, decode_scope


def _slots(conn: Any, values: Iterable[Any]) -> str:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    return ",".join(marker for _ in values)


def _context(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _hand_started(conn: Any, sessions: tuple[str, ...]) -> set[str]:
    if not sessions:
        return set()
    rows = conn.execute(
        "SELECT session_id FROM harness_sessions "
        f"WHERE launch_origin = 'operator' AND session_id IN ({_slots(conn, sessions)})",
        sessions,
    ).fetchall()
    return {str(row[0]) for row in rows}


def _claimed_items(conn: Any, sessions: tuple[str, ...]) -> dict[str, int]:
    """The item each asking session holds a live work claim on."""
    if not sessions or not _table_exists(conn, "work_claims"):
        return {}
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT session_id, scope FROM work_claims "
        f"WHERE target_kind = {marker} AND released_at IS NULL "
        f"AND session_id IN ({_slots(conn, sessions)}) ORDER BY claimed_at, id",
        (TARGET_KIND_ITEM, *sessions),
    ).fetchall()
    claimed: dict[str, int] = {}
    for row in rows:
        item_id = decode_scope(row[1]).get("item_id")
        if item_id is not None:
            claimed.setdefault(str(row[0]), int(item_id))
    return claimed


def _item_projects(conn: Any, item_ids: tuple[int, ...]) -> dict[int, int]:
    if not item_ids:
        return {}
    rows = conn.execute(
        f"SELECT id, project_id FROM items WHERE id IN ({_slots(conn, item_ids)})",
        item_ids,
    ).fetchall()
    return {int(row[0]): int(row[1]) for row in rows}


def visible_questions(
    conn: Any,
    viewer_session_id: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    viewer_actor_id: int | None,
) -> dict[int, str]:
    """Map each request the viewer sees to its unattended note ("" if none).

    *rows* carry ``id``, ``project_id``, ``audience_id``,
    ``requesting_session_id`` and ``subject_context``. A watched request
    that left ``pending`` passes the same rule, so its outcome reaches the
    seat that covers it now.
    """
    from yoke_core.domain.audiences import includes_actor
    from yoke_core.domain.project_identity import resolve_project_slug

    records = [dict(row) for row in rows]
    askers = tuple(
        dict.fromkeys(str(row["requesting_session_id"] or "") for row in records)
    )
    hand = _hand_started(conn, askers)
    claimed = _claimed_items(conn, askers)
    work: dict[int, int | None] = {}
    for row in records:
        item = _context(row["subject_context"]).get("item_id")
        item = (
            item if item is not None else claimed.get(str(row["requesting_session_id"]))
        )
        work[int(row["id"])] = int(item) if item is not None else None
    item_ids = tuple({value for value in work.values() if value is not None})
    projects = _item_projects(conn, item_ids)
    links = item_document_links(conn, item_ids)
    claims = live_steering_claims(conn)
    project_seats = {
        int(claim["scope"][PROJECT_KEY])
        for claim in claims
        if str(claim["session_id"]) == viewer_session_id
        and PROJECT_KEY in claim["scope"]
        and DOCUMENT_KEY not in claim["scope"]
    }
    visible: dict[int, str] = {}
    for row in records:
        request_id = int(row["id"])
        asker = str(row["requesting_session_id"] or "")
        if asker == viewer_session_id:
            visible[request_id] = ""
            continue
        if asker in hand:
            continue
        if row["project_id"] is None:
            if viewer_actor_id is not None and includes_actor(
                conn, row["audience_id"], viewer_actor_id
            ):
                visible[request_id] = ""
            continue
        item = work[request_id]
        known = item if item in projects else None
        target = item_coverage_target(
            conn,
            project_id=projects[known] if known is not None else int(row["project_id"]),
            item_id=known,
            links=links,
        )
        seat = covering_seat(conn, target, claims=claims)
        if seat is not None:
            if str(seat["session_id"]) == viewer_session_id:
                visible[request_id] = ""
            continue
        owner = int(target.get(DOCUMENT_PROJECT_KEY, target[PROJECT_KEY]))
        if owner in project_seats:
            name = target.get(DOCUMENT_KEY) or resolve_project_slug(conn, owner)
            visible[request_id] = f"unattended: no live seat for {name}"
    return visible


__all__ = ["visible_questions"]
