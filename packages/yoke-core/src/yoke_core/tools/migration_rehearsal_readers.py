"""Read restored rows through product surfaces after boot convergence."""

from __future__ import annotations

from typing import Any, Callable

from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_contracts.items_projection import DEFAULT_GET_FIELDS
from yoke_core.domain import db_backend
from yoke_core.domain.deployment_start_timing import (
    start_step,
    timed_preparation as timed,
)
from yoke_core.domain.handlers import (
    frontier_list,
    items_listing,
    orchestration,
    reads,
    sessions_list,
)
from yoke_core.domain.session_launch_history_page import read_launch_page
from yoke_core.domain.session_launch_projection import public_launch_record
from yoke_core.domain.session_launch_store import get_launch, launch_read_batch
from yoke_core.domain.sessions_list_read import session_read_batch
from yoke_core.domain.items_queries import item_field_read_batch
from yoke_core.domain.session_message_attempt_reads import (
    message_attempt_evidence,
    message_attempt_read_batch,
)


READ_BATCH_SIZE = 100


def _batches(rows):
    for start in range(0, len(rows), READ_BATCH_SIZE):
        yield [row[0] for row in rows[start : start + READ_BATCH_SIZE]]


def checked(function: str, handler: Callable, payload=None, target=None) -> dict:
    """A handler refusal fails proof, including a caught decode error."""
    outcome = handler(
        FunctionCallRequest(
            function=function,
            actor={"session_id": "migration-rehearsal"},
            target=target or {"kind": "global"},
            payload=payload or {},
        )
    )
    if not outcome.primary_success or outcome.error is not None:
        error = outcome.error
        raise RuntimeError(
            f"{function}: {error.code}: {error.message}"
            if error
            else f"{function}: unsuccessful outcome"
        )
    return outcome.result_payload


def verify_migrated_readers(conn: Any, copy_dsn: str) -> str | None:
    """Exercise every copied record beyond the newest-N list window."""
    operation = "sessions.list"
    try:
        with db_backend.bound_pg_dsn(copy_dsn):
            session_ids = conn.execute(
                "SELECT session_id FROM harness_sessions ORDER BY session_id"
            ).fetchall()
            conn.rollback()
            checked(operation, sessions_list.handle_sessions_list)
            with start_step(
                "fleet_readers_sessions", heartbeat=True, record_count=len(session_ids)
            ) as progress:
                for ids in _batches(session_ids):
                    with session_read_batch(ids):
                        for session_id in ids:
                            checked(
                                operation,
                                sessions_list.handle_sessions_list,
                                {"session_id": session_id},
                            )
                            progress["completed_count"] += 1
            operation = "frontier.list"
            timed(
                "fleet_readers_frontier",
                checked,
                operation,
                frontier_list.handle_frontier_list,
            )
            operation = "board.data.get"
            timed(
                "fleet_readers_board",
                checked,
                operation,
                orchestration.handle_board_data_get,
            )
            projects = conn.execute(
                "SELECT id,slug FROM projects ORDER BY id"
            ).fetchall()
            for project_id, slug in projects:
                operation = f"session_control.launch.list project={slug}"
                with start_step(f"fleet_readers_launch_pages:{slug}", heartbeat=True):
                    cursor = None
                    while True:
                        page = read_launch_page(
                            conn, project_id=project_id, cursor=cursor
                        )
                        cursor = page["next_cursor"]
                        if cursor is None:
                            break
                operation = f"items.list.run project={slug}"
                timed(
                    f"fleet_readers_item_list:{slug}",
                    checked,
                    "items.list.run",
                    items_listing.handle_items_list,
                    {"project": slug},
                )
            launch_ids = conn.execute(
                "SELECT launch_id FROM session_launches ORDER BY launch_id"
            ).fetchall()
            operation = "session_control.launch.get batch"
            with start_step(
                "fleet_readers_launches", heartbeat=True, record_count=len(launch_ids)
            ) as progress:
                for ids in _batches(launch_ids):
                    with launch_read_batch(conn, ids):
                        for launch_id in ids:
                            operation = f"session_control.launch.get launch={launch_id}"
                            public_launch_record(get_launch(conn, str(launch_id)))
                            progress["completed_count"] += 1
            message_ids = conn.execute(
                "SELECT DISTINCT message_id FROM session_message_attempts ORDER BY message_id"
            ).fetchall()
            operation = "messages.get attempts batch"
            with start_step(
                "fleet_readers_message_attempts",
                heartbeat=True,
                record_count=len(message_ids),
            ) as progress:
                for ids in _batches(message_ids):
                    with message_attempt_read_batch(conn, ids):
                        for message_id in ids:
                            operation = f"messages.get attempts message={message_id}"
                            message_attempt_evidence(conn, str(message_id))
                            progress["completed_count"] += 1
            item_ids = conn.execute("SELECT id FROM items ORDER BY id").fetchall()
            conn.rollback()
            operation = "items.get.run batch"
            with start_step(
                "fleet_readers_items", heartbeat=True, record_count=len(item_ids)
            ) as progress:
                for ids in _batches(item_ids):
                    with item_field_read_batch(conn, ids, DEFAULT_GET_FIELDS):
                        for item_id in ids:
                            operation = f"items.get.run item={item_id}"
                            checked(
                                "items.get.run",
                                reads.handle_items_get,
                                target={"kind": "item", "item_id": item_id},
                            )
                            progress["completed_count"] += 1
    except BaseException as exc:  # noqa: BLE001 -- copy verdict
        from yoke_core.domain.migration_fleet_declared_plan import redact_dsn

        return redact_dsn(f"{operation}: {type(exc).__name__}: {exc}", copy_dsn)
    print(
        "READERS: sessions, frontier, board, launches, message attempts and items passed",
        flush=True,
    )
    return None
