"""Atomic registration and binding for task-scoped item path claims."""

from __future__ import annotations

from typing import Any, Iterable, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.path_claim_task_bindings import (
    PathClaimTaskBindingError,
    bind_claim_to_task,
    validate_task_binding_target,
)
from yoke_core.domain.path_claim_task_coverage import task_budget_paths
from yoke_core.domain.path_claims import get_claim
from yoke_core.domain.path_claims_register_symlink import (
    emit_decisions,
    expand_for_registration,
)
from yoke_core.domain.path_claims_register import register_for_item


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _matching_exception(
    conn: Any,
    *,
    item_id: int,
    task_num: int,
    integration_target: str,
    exception_reason: str,
) -> int | None:
    marker = _p(conn)
    row = conn.execute(
        "SELECT pc.id FROM path_claims pc "
        "JOIN path_claim_task_bindings b ON b.claim_id = pc.id "
        f"WHERE b.epic_id = {marker} AND b.task_num = {marker} "
        f"AND pc.integration_target = {marker} "
        "AND pc.mode = 'exception' "
        f"AND TRIM(pc.exception_reason) = {marker} "
        "AND pc.state IN ('planned','blocked','active') "
        "ORDER BY pc.id DESC LIMIT 1",
        (
            int(item_id),
            int(task_num),
            str(integration_target),
            str(exception_reason).strip(),
        ),
    ).fetchone()
    return int(row[0]) if row is not None else None


def _item_project_id(conn: Any, item_id: int) -> int:
    row = conn.execute(
        f"SELECT project_id FROM items WHERE id = {_p(conn)}",
        (int(item_id),),
    ).fetchone()
    if row is None or row[0] is None:
        raise PathClaimTaskBindingError(
            f"item YOK-{item_id} has no project for path registration"
        )
    return int(row[0])


def _claim_ids(conn: Any, item_id: int) -> set[int]:
    rows = conn.execute(
        f"SELECT id FROM path_claims WHERE owner_kind = 'item' "
        f"AND owner_item_id = {_p(conn)}",
        (int(item_id),),
    ).fetchall()
    return {int(row[0]) for row in rows}


def _latest_amendment_id(conn: Any, claim_ids: set[int]) -> int:
    if not claim_ids:
        return 0
    marker = _p(conn)
    placeholders = ",".join(marker for _ in claim_ids)
    row = conn.execute(
        "SELECT COALESCE(MAX(id), 0) FROM path_claim_amendments "
        f"WHERE claim_id IN ({placeholders})",
        tuple(sorted(claim_ids)),
    ).fetchone()
    return int(row[0] or 0)


def register_for_task(
    conn: Any,
    *,
    item_id: int,
    task_num: int,
    integration_target: str,
    paths: Iterable[str],
    upstream_claim_id: Optional[int] = None,
    actor_id: Optional[int] = None,
    session_id: Optional[str] = None,
    mode: str = "exclusive",
    exception_reason: Optional[str] = None,
    allow_planned: bool = False,
    directory_paths: Optional[Iterable[str]] = None,
    tentative_paths: Optional[Iterable[str]] = None,
) -> int:
    """Register/reuse and bind in one transaction."""
    try:
        validate_task_binding_target(
            conn,
            item_id=int(item_id),
            task_num=int(task_num),
        )
        project_id = _item_project_id(conn, int(item_id))
        path_list = list(paths)
        _expanded, symlink_decisions = expand_for_registration(
            conn,
            project_id,
            path_list,
        )
        existing_claim_ids = _claim_ids(conn, int(item_id))
        previous_amendment_id = _latest_amendment_id(
            conn,
            existing_claim_ids,
        )
        if mode == "exception":
            budget = task_budget_paths(conn, int(item_id), int(task_num))
            if budget:
                raise PathClaimTaskBindingError(
                    f"Epic task {item_id}/{task_num} has a persisted file "
                    "budget and cannot use a no-path exception"
                )
            existing = _matching_exception(
                conn,
                item_id=int(item_id),
                task_num=int(task_num),
                integration_target=integration_target,
                exception_reason=str(exception_reason or ""),
            )
            if existing is not None:
                conn.commit()
                return existing
        claim_id = register_for_item(
            conn,
            item_id=int(item_id),
            integration_target=integration_target,
            paths=path_list,
            upstream_claim_id=upstream_claim_id,
            actor_id=actor_id,
            session_id=session_id,
            mode=mode,
            exception_reason=exception_reason,
            allow_planned=allow_planned,
            directory_paths=directory_paths,
            tentative_paths=tentative_paths,
            task_num=int(task_num),
            commit=False,
            emit_events=False,
        )
        bind_claim_to_task(
            conn,
            claim_id=int(claim_id),
            item_id=int(item_id),
            task_num=int(task_num),
            commit=False,
        )
        from yoke_core.domain import path_claims_events as claim_events

        claim = get_claim(conn, int(claim_id))
        if int(claim_id) not in existing_claim_ids:
            claim_events.emit_registered(
                conn=conn,
                claim=claim,
                project=project_id,
            )
        else:
            row = conn.execute(
                "SELECT id FROM path_claim_amendments "
                f"WHERE claim_id = {_p(conn)} AND id > {_p(conn)} "
                "ORDER BY id DESC LIMIT 1",
                (int(claim_id), previous_amendment_id),
            ).fetchone()
            if row is not None:
                claim_events.emit_amended(
                    conn=conn,
                    claim=claim,
                    amendment_id=int(row[0]),
                    amendment_kind="widen",
                    payload={"task_num": int(task_num)},
                    reason="task registration reused concrete claim",
                    project=project_id,
                )
        emit_decisions(
            conn,
            claim_id=int(claim_id),
            project_id=project_id,
            item_id=int(item_id),
            session_id=session_id,
            decisions=symlink_decisions,
        )
        conn.commit()
        return int(claim_id)
    except Exception:
        conn.rollback()
        raise


__all__ = ["register_for_task"]
