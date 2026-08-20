"""Live overlap survey for claim-less direct workflow execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Optional
from uuid import uuid4

from yoke_contracts import conflict_survey as survey_contract
from yoke_core.domain import db_backend
from yoke_core.domain.conflict_survey_blockers import (
    direct_workflow_blockers,
    git_touched_paths,
)
from yoke_core.domain.conflict_survey_declared_paths import (
    CONFLICT_SURVEY_ORDERING,
    CONFLICT_SURVEY_SECTION,
    PENDING_REQUEST_KEY as _PENDING_REQUEST_KEY,
    classify_survey_payload,
    clean_path,
)
from yoke_core.domain.conflict_survey_models import ConflictMatch, ConflictSurvey
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.path_claims_dependency_resolver_coordination import (
    items_are_coordination_only,
)
from yoke_core.domain.schema_common import _table_exists

DIRECT_WORKFLOW_IDS = frozenset({"blitz", "dash"})


@dataclass(frozen=True)
class ConflictSurveyReservation:
    """Compare-and-swap marker for one in-flight survey request."""

    content: str
    previous_content: Optional[str]


@dataclass(frozen=True)
class RecordedConflictSurvey:
    """One durable survey row classified before callers consume it."""
    state: survey_contract.ConflictSurveyRecordState
    payload: Optional[dict[str, Any]] = None


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _dict_rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [str(column[0]) for column in cursor.description]
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def _clean_paths(paths: Iterable[str]) -> tuple[str, ...]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in paths:
        path = clean_path(value)
        if not path or path.endswith("/"):
            continue
        if path not in seen:
            cleaned.append(path)
            seen.add(path)
    if not cleaned:
        raise ValueError("conflict survey requires at least one intended path")
    return tuple(cleaned)


def _item(conn: Any, item_id: int) -> dict[str, Any]:
    marker = _p(conn)
    rows = _dict_rows(
        conn.execute(
            "SELECT id, project_id, workflow_id, status, COALESCE(spec, '') AS spec "
            f"FROM items WHERE id = {marker}",
            (int(item_id),),
        )
    )
    if not rows:
        raise LookupError(f"item {item_id} does not exist")
    row = rows[0]
    if str(row["workflow_id"]) not in DIRECT_WORKFLOW_IDS:
        raise ValueError(
            f"item {item_id} uses workflow {row['workflow_id']!r}; "
            "conflict survey is for Dash and Blitz execution"
        )
    return row


def _git_touched_paths(worktree_path: str, integration_target: str) -> list[str]:
    """Return the best-effort changed paths from a live item worktree."""
    return git_touched_paths(worktree_path, integration_target)


def survey_conflicts(
    conn: Any,
    *,
    item_id: int,
    touch_paths: Iterable[str],
    integration_target: str = "main",
) -> ConflictSurvey:
    """Survey registered and imminent overlaps for one direct work item."""
    clean_paths = _clean_paths(touch_paths)
    item = _item(conn, item_id)
    blockers = direct_workflow_blockers(
        conn,
        item=item,
        touch_paths=clean_paths,
        integration_target=integration_target,
    )
    blockers = [
        row
        for row in blockers
        if row.owner_item_id is None
        or not items_are_coordination_only(
            conn,
            item_a_id=int(item["id"]),
            item_b_id=row.owner_item_id,
        )
    ]
    blockers.sort(
        key=lambda row: (row.kind, row.owner_item_id or 0, row.path, row.detail),
    )
    digest_input = json.dumps(
        {
            "item_id": int(item_id),
            "integration_target": integration_target,
            "touch_paths": clean_paths,
            "blockers": [asdict(blocker) for blocker in blockers],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return ConflictSurvey(
        item_id=int(item_id),
        integration_target=integration_target,
        touch_paths=clean_paths,
        blockers=tuple(blockers),
        observed_at=iso8601_now(),
        fingerprint=hashlib.sha256(digest_input).hexdigest(),
    )


def reserve_conflict_survey_record(
    conn: Any,
    *,
    item_id: int,
) -> ConflictSurveyReservation:
    """Reserve the survey record before performing potentially slow work.

    A newer request replaces this marker immediately.  Its later result can
    then be written only when this reservation is still current.
    """
    marker = _p(conn)
    now = iso8601_now()
    existing = conn.execute(
        "SELECT content FROM item_sections "
        f"WHERE item_id = {marker} AND section_name = {marker}",
        (int(item_id), CONFLICT_SURVEY_SECTION),
    ).fetchone()
    previous_content = str(existing[0]) if existing is not None else None
    if existing is None:
        pending: dict[str, Any] = {}
    else:
        try:
            pending = json.loads(previous_content)
        except (TypeError, ValueError):
            pending = {}
        if isinstance(pending, dict):
            pending.pop(_PENDING_REQUEST_KEY, None)
            previous_content = json.dumps(
                pending,
                sort_keys=True,
                separators=(",", ":"),
            )
        else:
            pending = {}
    pending[_PENDING_REQUEST_KEY] = uuid4().hex
    content = json.dumps(pending, sort_keys=True, separators=(",", ":"))
    conn.execute(
        "INSERT INTO item_sections "
        "(item_id, section_name, content, ordering, source, created_at, updated_at) "
        f"VALUES ({', '.join(marker for _ in range(7))}) "
        "ON CONFLICT(item_id, section_name) DO UPDATE SET "
        "content = excluded.content, source = excluded.source, "
        "updated_at = excluded.updated_at",
        (
            int(item_id),
            CONFLICT_SURVEY_SECTION,
            content,
            CONFLICT_SURVEY_ORDERING,
            "direct-workflow",
            now,
            now,
        ),
    )
    conn.commit()
    return ConflictSurveyReservation(
        content=content,
        previous_content=previous_content,
    )


def record_conflict_survey(
    conn: Any,
    survey: ConflictSurvey,
    *,
    reservation: Optional[ConflictSurveyReservation] = None,
) -> bool:
    """Persist a survey, retaining only the result from the newest request."""
    marker = _p(conn)
    now = iso8601_now()
    content = json.dumps(survey.to_dict(), sort_keys=True, indent=2)
    if reservation is not None:
        cursor = conn.execute(
            "UPDATE item_sections SET content = " + marker + ", "
            "source = " + marker + ", updated_at = " + marker + " "
            "WHERE item_id = "
            + marker
            + " AND section_name = "
            + marker
            + " AND content = "
            + marker,
            (
                content,
                "direct-workflow",
                now,
                survey.item_id,
                CONFLICT_SURVEY_SECTION,
                reservation.content,
            ),
        )
        conn.commit()
        return cursor.rowcount == 1
    conn.execute(
        "INSERT INTO item_sections "
        "(item_id, section_name, content, ordering, source, created_at, updated_at) "
        f"VALUES ({', '.join(marker for _ in range(7))}) "
        "ON CONFLICT(item_id, section_name) DO UPDATE SET "
        "content = excluded.content, source = excluded.source, "
        "updated_at = excluded.updated_at",
        (
            survey.item_id,
            CONFLICT_SURVEY_SECTION,
            content,
            CONFLICT_SURVEY_ORDERING,
            "direct-workflow",
            now,
            now,
        ),
    )
    conn.commit()
    return True


def cancel_conflict_survey_reservation(
    conn: Any,
    *,
    item_id: int,
    reservation: ConflictSurveyReservation,
) -> None:
    """Restore the prior survey only when this request is still current."""
    marker = _p(conn)
    if reservation.previous_content is None:
        conn.execute(
            "DELETE FROM item_sections WHERE item_id = "
            + marker
            + " AND section_name = "
            + marker
            + " AND content = "
            + marker,
            (int(item_id), CONFLICT_SURVEY_SECTION, reservation.content),
        )
    else:
        conn.execute(
            "UPDATE item_sections SET content = "
            + marker
            + " WHERE item_id = "
            + marker
            + " AND section_name = "
            + marker
            + " AND content = "
            + marker,
            (
                reservation.previous_content,
                int(item_id),
                CONFLICT_SURVEY_SECTION,
                reservation.content,
            ),
        )
    conn.commit()


def read_recorded_survey_state(
    conn: Any, item_id: int,
) -> RecordedConflictSurvey:
    """Classify the durable row without confusing absence with bad data."""
    if not _table_exists(conn, "item_sections"):
        return RecordedConflictSurvey(survey_contract.DURABLE_ABSENT)
    marker = _p(conn)
    row = conn.execute(
        "SELECT content FROM item_sections "
        f"WHERE item_id = {marker} AND section_name = {marker}",
        (int(item_id), CONFLICT_SURVEY_SECTION),
    ).fetchone()
    if row is None:
        return RecordedConflictSurvey(survey_contract.DURABLE_ABSENT)
    state, payload = classify_survey_payload(row[0])
    return RecordedConflictSurvey(state, payload)


def read_recorded_survey(conn: Any, item_id: int) -> Optional[dict[str, Any]]:
    """Return a complete persisted survey envelope, or ``None``."""
    record = read_recorded_survey_state(conn, item_id)
    return record.payload if record.state == survey_contract.DURABLE_RECORDED else None


__all__ = [
    "CONFLICT_SURVEY_SECTION",
    "ConflictMatch",
    "ConflictSurvey",
    "ConflictSurveyReservation",
    "RecordedConflictSurvey",
    "cancel_conflict_survey_reservation",
    "read_recorded_survey",
    "read_recorded_survey_state",
    "record_conflict_survey",
    "reserve_conflict_survey_record",
    "survey_conflicts",
]
