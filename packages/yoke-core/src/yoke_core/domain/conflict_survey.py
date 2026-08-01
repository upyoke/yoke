"""Live overlap survey for claim-less direct workflow execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any, Iterable, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.conflict_survey_blockers import (
    clean_path,
    direct_workflow_blockers,
    git_touched_paths,
)
from yoke_core.domain.conflict_survey_models import ConflictMatch, ConflictSurvey
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.path_claims_dependency_resolver_coordination import (
    items_are_coordination_only,
)
from yoke_core.domain.schema_common import _table_exists

CONFLICT_SURVEY_SECTION = "Conflict Survey"
DIRECT_WORKFLOW_IDS = frozenset({"blitz", "dash"})


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


def record_conflict_survey(conn: Any, survey: ConflictSurvey) -> None:
    """Persist the latest survey as a machine-readable item section."""
    marker = _p(conn)
    now = iso8601_now()
    content = json.dumps(survey.to_dict(), sort_keys=True, indent=2)
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
            180,
            "direct-workflow",
            now,
            now,
        ),
    )
    conn.commit()


def read_recorded_survey(conn: Any, item_id: int) -> Optional[dict[str, Any]]:
    """Return the persisted survey envelope, or ``None``."""
    if not _table_exists(conn, "item_sections"):
        return None
    marker = _p(conn)
    row = conn.execute(
        "SELECT content FROM item_sections "
        f"WHERE item_id = {marker} AND section_name = {marker}",
        (int(item_id), CONFLICT_SURVEY_SECTION),
    ).fetchone()
    if row is None:
        return None
    try:
        parsed = json.loads(str(row[0]))
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


__all__ = [
    "CONFLICT_SURVEY_SECTION",
    "ConflictMatch",
    "ConflictSurvey",
    "read_recorded_survey",
    "record_conflict_survey",
    "survey_conflicts",
]
