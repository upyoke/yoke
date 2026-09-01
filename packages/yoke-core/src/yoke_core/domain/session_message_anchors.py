"""Which sessions each recipient anchor names.

Anchors union: every flag ADDS recipients rather than narrowing the ones
before it. Most anchors resolve through a live claim -- the work addresses
its own holder -- and ``session_ids`` is the fallback for a recipient no
claim names.

``steering`` is the one anchor that names a role instead of a session or a
piece of work. It resolves to whichever live seat covers the addressed
target, and to nobody when no seat is live; the send path treats that
emptiness as a park rather than a refusal, so the message waits for the
next seat instead of failing.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.session_control.models import RecipientSelector
from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_item_id, resolve_project
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_core.domain.work_claim_targets import TARGET_KIND_STEERING


#: Resolution evidence recorded for the role anchor.
STEERING_EVIDENCE = "steering"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _item_project_id(conn: Any, item_id: int) -> int:
    marker = _p(conn)
    row = conn.execute(
        f"SELECT project_id FROM items WHERE id={marker}", (item_id,)
    ).fetchone()
    if row is None:
        raise SessionMessageError("target_not_found", f"item id {item_id} not found")
    return int(row[0])


def _resolve_item_ref(conn: Any, raw: str) -> tuple[int, int]:
    try:
        item_id = resolve_item_id(conn, raw)
    except LookupError as exc:
        raise SessionMessageError(
            "target_not_found",
            str(exc),
            jsonpath="$.payload.selector.public_refs",
        ) from exc
    if item_id is None:
        raise SessionMessageError(
            "target_not_found",
            f"item anchor {raw!r} was not found; use a qualified public item ref",
            jsonpath="$.payload.selector.public_refs",
        )
    return int(item_id), _item_project_id(conn, int(item_id))


def _resolve_epic_task(conn: Any, raw: str) -> tuple[int, int, int]:
    epic_ref, separator, task_raw = str(raw).rpartition(":")
    if not separator or not task_raw.isdigit():
        raise SessionMessageError(
            "selector_invalid",
            f"epic-task anchor {raw!r} must be '<qualified-item-ref>:<task-num>'",
            jsonpath="$.payload.selector.epic_tasks",
        )
    epic_id, project_id = _resolve_item_ref(conn, epic_ref)
    task_num = int(task_raw)
    marker = _p(conn)
    exists = conn.execute(
        f"SELECT 1 FROM epic_tasks WHERE epic_id={marker} AND task_num={marker}",
        (epic_id, task_num),
    ).fetchone()
    if exists is None:
        raise SessionMessageError(
            "target_not_found", f"epic-task anchor {raw!r} was not found"
        )
    return epic_id, task_num, project_id


def _add_hit(
    hits: dict[str, list[tuple[str, int]]],
    session_id: str,
    evidence: str,
    project_id: int,
) -> None:
    hits.setdefault(session_id, []).append((evidence, project_id))


def anchor_hits(
    conn: Any,
    selector: RecipientSelector,
    sessions: dict[str, dict[str, Any]],
    claims: list[dict[str, Any]],
    *,
    steering_target: Mapping[str, Any] | None = None,
) -> dict[str, list[tuple[str, int]]]:
    hits: dict[str, list[tuple[str, int]]] = {}
    for session_id in selector.session_ids:
        row = sessions.get(session_id)
        if row is not None:
            _add_hit(hits, session_id, f"session:{session_id}", int(row["project_id"]))
    for raw in selector.public_refs:
        item_id, project_id = _resolve_item_ref(conn, raw)
        for claim in claims:
            if claim["target_kind"] == "item" and int(claim["item_id"]) == item_id:
                _add_hit(hits, str(claim["session_id"]), f"item:{raw}", project_id)
    for raw in selector.epic_tasks:
        epic_id, task_num, project_id = _resolve_epic_task(conn, raw)
        for claim in claims:
            if (
                claim["target_kind"] == "epic_task"
                and int(claim["epic_id"]) == epic_id
                and int(claim["task_num"]) == task_num
            ):
                _add_hit(hits, str(claim["session_id"]), f"epic_task:{raw}", project_id)
    for process_key in selector.process_keys:
        for claim in claims:
            if (
                claim["target_kind"] == "process"
                and claim["process_key"] == process_key
            ):
                _add_hit(
                    hits,
                    str(claim["session_id"]),
                    f"process:{process_key}",
                    int(claim["anchor_project_id"]),
                )
    for raw in selector.projects:
        try:
            identity = resolve_project(conn, raw, required=True)
        except LookupError as exc:
            raise SessionMessageError(
                "target_not_found",
                str(exc),
                jsonpath="$.payload.selector.projects",
            ) from exc
        assert identity is not None
        for session_id, row in sessions.items():
            if int(row["project_id"]) == identity.id:
                _add_hit(hits, session_id, f"project:{identity.slug}", identity.id)
        for claim in claims:
            if (
                claim["target_kind"] == TARGET_KIND_STEERING
                and int(claim["anchor_project_id"]) == identity.id
            ):
                _add_hit(
                    hits,
                    str(claim["session_id"]),
                    f"project:{identity.slug}",
                    identity.id,
                )
    if selector.universe:
        for session_id, row in sessions.items():
            _add_hit(hits, session_id, "universe", int(row["project_id"]))
    if selector.steering and steering_target is not None:
        from yoke_core.domain.steering_scope_coverage import (
            PROJECT_KEY,
            covering_seat,
        )

        seat = covering_seat(conn, steering_target)
        if seat is not None and str(seat["session_id"]) in sessions:
            _add_hit(
                hits,
                str(seat["session_id"]),
                STEERING_EVIDENCE,
                int(steering_target[PROJECT_KEY]),
            )
    return hits


__all__ = ["STEERING_EVIDENCE", "anchor_hits"]


