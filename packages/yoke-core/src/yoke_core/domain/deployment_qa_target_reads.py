"""Frozen QA targets and current producer receipts for a presentation read."""

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_qa_presentation_reads import (
    presentation_active,
    presentation_read,
)


def _p(conn):
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row(cursor, value):
    if value is None:
        return None
    if hasattr(value, "keys"):
        return dict(value)
    return dict(
        zip(
            (str(getattr(col, "name", None) or col[0]) for col in cursor.description),
            value,
            strict=True,
        )
    )


def _decode_stored_target(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, Mapping):
        return dict(raw)
    try:
        decoded = json.loads(str(raw or ""))
    except (TypeError, ValueError):
        return None
    return dict(decoded) if isinstance(decoded, dict) else None


def first_materialized_execution_target(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
) -> dict[str, Any] | None:
    """The target stamped onto this subject at first materialization.

    Environment URL and settings remain live tables, so recomputing the
    snapshot mid-run re-keys ``execution_target_digest`` and drops already
    recorded cases out of scope. The first materialized row is the freeze
    while that subject's producer receipt is unchanged. A newer ready
    attempt is a new identity and must not reuse this snapshot.
    """

    def read():
        from yoke_core.domain.deployment_qa_presentation_facts import (
            stage_requirement_rows,
        )

        rows = stage_requirement_rows(conn, str(run_id), str(stage_name))
        if rows is not None:
            targets = {}
            for row in rows:
                if row["execution_target_json"] is not None:
                    targets.setdefault(
                        int(row["deployment_member_item_id"] or 0), dict(row)
                    )
            return targets
        batch = presentation_active()
        member_filter = (
            "" if batch else f"AND COALESCE(deployment_member_item_id,0)={_p(conn)} "
        )
        rows = conn.execute(
            "SELECT deployment_member_item_id,execution_target_json FROM qa_requirements "
            f"WHERE deployment_run_id={_p(conn)} AND deployment_stage={_p(conn)} "
            f"{member_filter}AND execution_target_json IS NOT NULL ORDER BY "
            "CASE WHEN method_id IS NOT NULL THEN 0 ELSE 1 END, id"
            + ("" if batch else " LIMIT 1"),
            (str(run_id), str(stage_name))
            if batch
            else (str(run_id), str(stage_name), int(member_item_id or 0)),
        ).fetchall()
        targets = {}
        for row in rows:
            targets.setdefault(int(row["deployment_member_item_id"] or 0), dict(row))
        return targets

    rows = presentation_read(
        conn, ("qa_frozen_targets", str(run_id), str(stage_name)), read
    )
    row = rows.get(int(member_item_id or 0))
    if row is None:
        return None
    frozen = _decode_stored_target(row["execution_target_json"])
    if frozen is None:
        raise ValueError(
            f"deployment run {run_id!r} stage {stage_name!r} member "
            f"{member_item_id!r} has an unreadable frozen execution target"
        )
    return frozen


def _read_latest_ready_receipt_id(
    conn: Any, *, run_id: str, source_stage: str
) -> int | None:
    from yoke_core.domain.deployment_qa_presentation_facts import producer_receipts

    rows = producer_receipts(conn, run_id, source_stage)
    if rows is not None:
        return next((int(row["id"]) for row in rows if row["status"] == "ready"), None)
    cursor = conn.execute(
        f"SELECT id FROM deployment_stage_receipts WHERE run_id={_p(conn)} "
        f"AND stage_name={_p(conn)} AND status='ready' "
        "ORDER BY attempt_number DESC LIMIT 1",
        (str(run_id), str(source_stage)),
    )
    row = _row(cursor, cursor.fetchone())
    return int(row["id"]) if row is not None else None


def _latest_ready_receipt_id(conn, *, run_id, source_stage):
    return presentation_read(
        conn,
        ("qa_latest_receipt", run_id, source_stage),
        lambda: _read_latest_ready_receipt_id(
            conn, run_id=run_id, source_stage=source_stage
        ),
    )
