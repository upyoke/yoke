"""Live overlap survey for claim-less direct workflow execution."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import PurePosixPath
from typing import Any, Iterable, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.conflict_survey_models import ConflictMatch, ConflictSurvey
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.file_budget_paths import extract_file_budget_paths
from yoke_core.domain.schema_common import _table_exists

CONFLICT_SURVEY_SECTION = "Conflict Survey"
DIRECT_WORKFLOW_IDS = frozenset({"blitz", "dash"})
_TERMINAL_STATUSES = frozenset({"done", "cancelled", "stopped"})
_NON_TERMINAL_CLAIM_STATES = ("planned", "blocked", "active")

def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _dict_rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [str(column[0]) for column in cursor.description]
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def _clean_path(value: Any) -> str:
    path = str(value).strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path.lstrip("/")


def _clean_paths(paths: Iterable[str]) -> tuple[str, ...]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in paths:
        path = _clean_path(value)
        if not path or path.endswith("/"):
            continue
        if path not in seen:
            cleaned.append(path)
            seen.add(path)
    if not cleaned:
        raise ValueError("conflict survey requires at least one intended path")
    return tuple(cleaned)


def _overlap(left: str, right: str) -> bool:
    """Treat equal files and ancestor directory scopes as overlap."""
    left_path = PurePosixPath(left)
    right_path = PurePosixPath(right)
    return (
        left_path == right_path
        or left_path in right_path.parents
        or right_path in left_path.parents
    )


def _matching_path(touch_paths: tuple[str, ...], candidates: Iterable[str]) -> str:
    for candidate in candidates:
        clean = _clean_path(candidate)
        for intended in touch_paths:
            if clean and _overlap(intended, clean):
                return clean
    return ""


def _item(conn: Any, item_id: int) -> dict[str, Any]:
    marker = _p(conn)
    rows = _dict_rows(conn.execute(
        "SELECT id, project_id, workflow_id, status, COALESCE(spec, '') AS spec "
        f"FROM items WHERE id = {marker}",
        (int(item_id),),
    ))
    if not rows:
        raise LookupError(f"item {item_id} does not exist")
    row = rows[0]
    if str(row["workflow_id"]) not in DIRECT_WORKFLOW_IDS:
        raise ValueError(
            f"item {item_id} uses workflow {row['workflow_id']!r}; "
            "conflict survey is for Dash and Blitz execution"
        )
    return row


def _path_claim_blockers(
    conn: Any,
    *,
    item: dict[str, Any],
    touch_paths: tuple[str, ...],
    integration_target: str,
) -> list[ConflictMatch]:
    tables = ("path_claims", "path_claim_targets", "path_targets")
    if not all(_table_exists(conn, table) for table in tables):
        return []
    marker = _p(conn)
    state_markers = ", ".join(marker for _ in _NON_TERMINAL_CLAIM_STATES)
    rows = _dict_rows(conn.execute(
        "SELECT pc.id, pc.state, pc.owner_item_id, pc.item_id, "
        "pt.path_string FROM path_claims pc "
        "JOIN path_claim_targets pct ON pct.claim_id = pc.id "
        "JOIN path_targets pt ON pt.id = pct.target_id "
        f"WHERE pc.integration_target = {marker} "
        f"AND pc.state IN ({state_markers}) "
        f"AND pt.project_id = {marker}",
        (
            integration_target,
            *_NON_TERMINAL_CLAIM_STATES,
            int(item["project_id"]),
        ),
    ))
    blockers: list[ConflictMatch] = []
    for row in rows:
        owner = row.get("owner_item_id") or row.get("item_id")
        if owner is not None and int(owner) == int(item["id"]):
            continue
        matched = _matching_path(touch_paths, [str(row["path_string"])])
        if matched:
            blockers.append(ConflictMatch(
                kind="path_claim",
                owner_item_id=int(owner) if owner is not None else None,
                path=matched,
                state=str(row["state"]),
                detail=f"path claim {row['id']} wins over claim-less work",
            ))
    return blockers


def _git_touched_paths(worktree_path: str, integration_target: str) -> list[str]:
    if not worktree_path:
        return []
    try:
        result = subprocess.run(
            [
                "git", "-C", worktree_path, "diff", "--name-only",
                f"{integration_target}...HEAD",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _item_coordination_blockers(
    conn: Any,
    *,
    item: dict[str, Any],
    touch_paths: tuple[str, ...],
    integration_target: str,
) -> list[ConflictMatch]:
    marker = _p(conn)
    worktree_select = (
        ", iw.path AS worktree_path, iw.branch AS worktree_branch"
        if _table_exists(conn, "item_worktrees")
        else ", NULL AS worktree_path, NULL AS worktree_branch"
    )
    worktree_join = (
        " LEFT JOIN item_worktrees iw ON iw.item_id = i.id "
        "AND iw.state = 'active'"
        if _table_exists(conn, "item_worktrees")
        else ""
    )
    claim_select = (
        ", wc.id AS work_claim_id"
        if _table_exists(conn, "work_claims")
        else ", NULL AS work_claim_id"
    )
    claim_join = (
        " LEFT JOIN work_claims wc ON wc.item_id = i.id "
        "AND wc.target_kind = 'item' AND wc.released_at IS NULL"
        if _table_exists(conn, "work_claims")
        else ""
    )
    doc_select = (
        ", COALESCE(sd.content, '') AS execution_document"
        if all(_table_exists(conn, table)
               for table in ("item_strategy_docs", "strategy_docs"))
        else ", '' AS execution_document"
    )
    doc_join = (
        " LEFT JOIN item_strategy_docs isl ON isl.item_id = i.id "
        "LEFT JOIN strategy_docs sd ON sd.project_id = isl.project_id "
        "AND sd.slug = isl.strategy_doc_slug"
        if "sd.content" in doc_select else ""
    )
    rows = _dict_rows(conn.execute(
        "SELECT i.id, i.status, COALESCE(i.spec, '') AS spec"
        f"{worktree_select}{claim_select}{doc_select} FROM items i"
        f"{worktree_join}{claim_join}{doc_join} "
        f"WHERE i.project_id = {marker} AND i.id <> {marker}",
        (int(item["project_id"]), int(item["id"])),
    ))
    blockers: list[ConflictMatch] = []
    seen: set[tuple[str, int, str]] = set()
    for row in rows:
        if str(row["status"]) in _TERMINAL_STATUSES:
            continue
        declared = extract_file_budget_paths(
            f"{row['spec']}\n{row['execution_document']}"
        )
        worktree_paths = _git_touched_paths(
            str(row.get("worktree_path") or ""), integration_target,
        )
        matched = _matching_path(touch_paths, [*worktree_paths, *declared])
        if not matched:
            continue
        if row.get("work_claim_id") is not None:
            kind, state = "work_claim", "active"
            detail = f"active work claim {row['work_claim_id']}"
        elif row.get("worktree_path"):
            kind, state = "worktree", "active"
            detail = f"in-flight branch {row.get('worktree_branch') or ''}".strip()
        else:
            kind, state = "frontier_scope", str(row["status"])
            detail = "non-terminal item declares this path in its File Budget"
        key = (kind, int(row["id"]), matched)
        if key not in seen:
            blockers.append(ConflictMatch(
                kind=kind,
                owner_item_id=int(row["id"]),
                path=matched,
                state=state,
                detail=detail,
            ))
            seen.add(key)
    return blockers


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
    blockers = [
        *_path_claim_blockers(
            conn,
            item=item,
            touch_paths=clean_paths,
            integration_target=integration_target,
        ),
        *_item_coordination_blockers(
            conn,
            item=item,
            touch_paths=clean_paths,
            integration_target=integration_target,
        ),
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
