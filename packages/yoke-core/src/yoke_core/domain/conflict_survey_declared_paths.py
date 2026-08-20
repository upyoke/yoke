"""Recorded conflict-survey touch paths as a shared coordination signal.

A direct-workflow item records its intended edit targets before it has a
worktree, a path claim, or a File Budget. For a workflow that resolves
both of those policies to optional, the recorded survey is the only
durable statement of intent that exists, and the window between
recording it and creating the lane is otherwise unguarded.

This module owns that row — where it is stored, how a stored payload is
classified, and how one item's declared paths compare with another's —
and it sits below every reader so each can consult declared intent
without importing the others. :mod:`conflict_survey` writes the row and
surveys on top of it, :mod:`conflict_survey_blockers` reads other items'
declared paths while surveying, and :mod:`path_claims_overlap_survey`
reads them while classifying a path claim. Visibility therefore runs in
both directions: a survey sees registered claims, and a registering
claim sees declared surveys.

Terminal and frozen items declare nothing. Terminal work coordinates
nothing by definition, and a frozen item's intent is parked exactly as
its path claims are dormant — surfacing it would let parked coordination
block live work through a second door.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable, Optional, Sequence, Tuple

from yoke_contracts import conflict_survey as survey_contract
from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists, _table_exists

CONFLICT_SURVEY_SECTION = "Conflict Survey"
CONFLICT_SURVEY_ORDERING = 180
PENDING_REQUEST_KEY = "pending_request"
TERMINAL_STATUSES = frozenset({"done", "cancelled", "stopped"})


@dataclass(frozen=True)
class DeclaredSurvey:
    """One live item's recorded intent on an integration target."""

    item_id: int
    status: str
    integration_target: str
    paths: Tuple[str, ...]


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def clean_path(value: Any) -> str:
    """Normalize a path before comparing it with a declared scope."""
    path = str(value).strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path.lstrip("/")


def path_scopes_overlap(left: str, right: str) -> bool:
    """Treat equal files and ancestor directory scopes as overlap."""
    left_path = PurePosixPath(left)
    right_path = PurePosixPath(right)
    return (
        left_path == right_path
        or left_path in right_path.parents
        or right_path in left_path.parents
    )


def matching_scope(touch_paths: Sequence[str], candidates: Iterable[str]) -> str:
    """Return the first candidate path that overlaps the declared scope."""
    for candidate in candidates:
        clean = clean_path(candidate)
        for intended in touch_paths:
            if clean and path_scopes_overlap(intended, clean):
                return clean
    return ""


def classify_survey_payload(
    content: Any,
) -> Tuple[survey_contract.ConflictSurveyRecordState, Optional[dict[str, Any]]]:
    """Classify a stored survey row without confusing absence with bad data."""
    try:
        parsed = json.loads(str(content))
    except (TypeError, ValueError):
        return survey_contract.DURABLE_UNREADABLE, None
    if not isinstance(parsed, dict):
        return survey_contract.DURABLE_UNREADABLE, None
    if PENDING_REQUEST_KEY in parsed:
        return survey_contract.DURABLE_PENDING, None
    paths = parsed.get("touch_paths")
    valid_paths = isinstance(paths, list) and bool(paths) and all(
        isinstance(path, str) and clean_path(path) for path in paths
    )
    if (
        parsed.get("schema") != 1
        or not valid_paths
        or not isinstance(parsed.get("fingerprint"), str)
    ):
        return survey_contract.DURABLE_UNREADABLE, None
    return survey_contract.DURABLE_RECORDED, parsed


def _recorded_paths(payload: dict[str, Any]) -> Tuple[str, ...]:
    return tuple(
        path for path in (clean_path(v) for v in payload["touch_paths"]) if path
    )


def declared_surveys(
    conn: Any,
    *,
    project_id: int,
    integration_target: str,
    exclude_item_id: Optional[int] = None,
) -> list[DeclaredSurvey]:
    """Return every live item's recorded survey on one integration target.

    A pending or unreadable row declares nothing, so only a fully
    recorded payload contributes, and a survey taken against a different
    integration target is a different door lock entirely.
    """
    if not all(_table_exists(conn, table) for table in ("item_sections", "items")):
        return []
    marker = _p(conn)
    terminal = tuple(sorted(TERMINAL_STATUSES))
    terminal_markers = ", ".join(marker for _ in terminal)
    frozen_filter = (
        " AND COALESCE(i.frozen, 0) = 0"
        if _column_exists(conn, "items", "frozen")
        else ""
    )
    exclusion = f" AND i.id <> {marker}" if exclude_item_id is not None else ""
    params: list[Any] = [CONFLICT_SURVEY_SECTION, int(project_id), *terminal]
    if exclude_item_id is not None:
        params.append(int(exclude_item_id))
    rows = conn.execute(
        "SELECT s.item_id AS item_id, i.status AS status, s.content AS content "
        "FROM item_sections s JOIN items i ON i.id = s.item_id "
        f"WHERE s.section_name = {marker} AND i.project_id = {marker} "
        f"AND i.status NOT IN ({terminal_markers})"
        f"{frozen_filter}{exclusion}",
        tuple(params),
    ).fetchall()
    surveys: list[DeclaredSurvey] = []
    for row in rows:
        item_id, status, content = (
            (row["item_id"], row["status"], row["content"])
            if hasattr(row, "keys")
            else row
        )
        state, payload = classify_survey_payload(content)
        if state != survey_contract.DURABLE_RECORDED or payload is None:
            continue
        if str(payload.get("integration_target") or "") != integration_target:
            continue
        paths = _recorded_paths(payload)
        if paths:
            surveys.append(
                DeclaredSurvey(
                    item_id=int(item_id),
                    status=str(status),
                    integration_target=integration_target,
                    paths=paths,
                )
            )
    return surveys


__all__ = [
    "CONFLICT_SURVEY_ORDERING",
    "CONFLICT_SURVEY_SECTION",
    "PENDING_REQUEST_KEY",
    "TERMINAL_STATUSES",
    "DeclaredSurvey",
    "classify_survey_payload",
    "clean_path",
    "declared_surveys",
    "matching_scope",
    "path_scopes_overlap",
]
