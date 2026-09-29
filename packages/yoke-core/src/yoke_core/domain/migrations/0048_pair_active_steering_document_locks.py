"""Bind live document locks to the steering seats that already hold them.

Older live locks have no stored seat identity. An explicit document seat names
its lock by slug; after those are assigned, a sole project seat and sole
remaining lock in one session/project are also unambiguous. Already paired
locks are left intact, including rows written while this entry was pending.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.schema_common import _add_column_if_not_exists, _table_exists
from yoke_core.domain.work_claim_targets import decode_scope


def _marker(conn: Any) -> str:
    return "%s" if connection_is_postgres(conn) else "?"


def apply(conn: Any) -> None:
    if not _table_exists(conn, "strategy_doc_claims") or not _table_exists(
        conn, "work_claims"
    ):
        return
    _add_column_if_not_exists(
        conn, "strategy_doc_claims", "steering_claim_id", "INTEGER DEFAULT NULL"
    )
    seats: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for raw in conn.execute(
        "SELECT id, session_id, scope FROM work_claims "
        "WHERE target_kind = 'steering' AND released_at IS NULL"
    ).fetchall():
        row = dict(raw)
        scope = decode_scope(row["scope"])
        seats.setdefault((str(row["session_id"]), int(scope["project_id"])), []).append(
            {"id": int(row["id"]), "document": scope.get("document")}
        )
    locks: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for raw in conn.execute(
        "SELECT id, owner_session_id, project_id, strategy_doc_slug, "
        "steering_claim_id FROM strategy_doc_claims "
        "WHERE owner_kind = 'session' AND released_at IS NULL"
    ).fetchall():
        row = dict(raw)
        locks.setdefault(
            (str(row["owner_session_id"]), int(row["project_id"])), []
        ).append(row)
    marker = _marker(conn)
    for owner, owned_locks in locks.items():
        held_seats = seats.get(owner, [])
        occupied = {
            int(lock["steering_claim_id"])
            for lock in owned_locks
            if lock["steering_claim_id"] is not None
        }
        unpaired = [lock for lock in owned_locks if lock["steering_claim_id"] is None]
        assignments: list[tuple[int, int]] = []
        for lock in list(unpaired):
            matching = [
                seat
                for seat in held_seats
                if seat["document"] == lock["strategy_doc_slug"]
            ]
            if len(matching) > 1 or (matching and matching[0]["id"] in occupied):
                raise AssertionError(
                    f"document lock {lock['id']} has ambiguous live steering seats; "
                    "release and reacquire the affected seat before deploying"
                )
            if matching:
                seat_id = matching[0]["id"]
                assignments.append((seat_id, int(lock["id"])))
                occupied.add(seat_id)
                unpaired.remove(lock)
        project_seats = [
            seat
            for seat in held_seats
            if not seat["document"] and seat["id"] not in occupied
        ]
        if project_seats and unpaired:
            if len(project_seats) != 1 or len(unpaired) != 1:
                raise AssertionError(
                    f"session {owner[0]} project {owner[1]} has ambiguous "
                    "project-seat document locks; release unrelated locks or "
                    "reacquire the seat with --plan-doc before deploying"
                )
            assignments.append((project_seats[0]["id"], int(unpaired[0]["id"])))
        for seat_id, lock_id in assignments:
            conn.execute(
                "UPDATE strategy_doc_claims "
                f"SET steering_claim_id = {marker} "
                f"WHERE id = {marker} AND steering_claim_id IS NULL",
                (seat_id, lock_id),
            )


def invariants(conn: Any) -> None:
    if not _table_exists(conn, "strategy_doc_claims"):
        return
    rows = conn.execute(
        "SELECT steering_claim_id, COUNT(*) AS n FROM strategy_doc_claims "
        "WHERE owner_kind = 'session' AND released_at IS NULL "
        "AND steering_claim_id IS NOT NULL GROUP BY steering_claim_id "
        "HAVING COUNT(*) > 1"
    ).fetchall()
    if rows:
        raise AssertionError("one live steering seat owns multiple document locks")
