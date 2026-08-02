"""Blocker discovery for direct-workflow conflict surveys."""

from __future__ import annotations

import subprocess
from pathlib import PurePosixPath
from typing import Any, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.conflict_survey_models import ConflictMatch
from yoke_core.domain.file_budget_paths import extract_file_budget_paths
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.workflow_definition_builders import (
    WORKFLOW_PATH_CLAIMS_OPTIONAL,
)
from yoke_core.domain.workflow_effective_policies import (
    load_item_effective_workflow_policies,
)

_NON_TERMINAL_CLAIM_STATES = ("planned", "blocked", "active")
_TERMINAL_STATUSES = frozenset({"done", "cancelled", "stopped"})


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _dict_rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [str(column[0]) for column in cursor.description]
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def clean_path(value: Any) -> str:
    """Normalize a path before comparing it with a declared scope."""
    path = str(value).strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path.lstrip("/")


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
        clean = clean_path(candidate)
        for intended in touch_paths:
            if clean and _overlap(intended, clean):
                return clean
    return ""


def _ignores_frozen_planning_scopes(conn: Any, item: dict[str, Any]) -> bool:
    """Whether an optional-path-claims Dash may proceed past frozen plans."""
    if str(item["workflow_id"]) != "dash":
        return False
    policies = load_item_effective_workflow_policies(conn, int(item["id"]))
    return policies.path_claims == WORKFLOW_PATH_CLAIMS_OPTIONAL


def _path_claim_blockers(
    conn: Any,
    *,
    item: dict[str, Any],
    touch_paths: tuple[str, ...],
    integration_target: str,
    ignore_frozen_planning_scopes: bool,
) -> list[ConflictMatch]:
    tables = ("path_claims", "path_claim_targets", "path_targets")
    if not all(_table_exists(conn, table) for table in tables):
        return []
    marker = _p(conn)
    state_markers = ", ".join(marker for _ in _NON_TERMINAL_CLAIM_STATES)
    rows = _dict_rows(
        conn.execute(
            "SELECT pc.id, pc.state, pc.owner_item_id, "
            "COALESCE(owner.frozen, 0) AS owner_frozen, pt.path_string "
            "FROM path_claims pc "
            "JOIN path_claim_targets pct ON pct.claim_id = pc.id "
            "JOIN path_targets pt ON pt.id = pct.target_id "
            "LEFT JOIN items owner ON owner.id = pc.owner_item_id "
            f"WHERE pc.integration_target = {marker} "
            f"AND pc.state IN ({state_markers}) "
            f"AND pt.project_id = {marker}",
            (
                integration_target,
                *_NON_TERMINAL_CLAIM_STATES,
                int(item["project_id"]),
            ),
        )
    )
    blockers: list[ConflictMatch] = []
    for row in rows:
        owner = row.get("owner_item_id")
        if owner is not None and int(owner) == int(item["id"]):
            continue
        if (
            ignore_frozen_planning_scopes
            and str(row["state"]) == "planned"
            and bool(row.get("owner_frozen"))
        ):
            continue
        matched = _matching_path(touch_paths, [str(row["path_string"])])
        if matched:
            blockers.append(
                ConflictMatch(
                    kind="path_claim",
                    owner_item_id=int(owner) if owner is not None else None,
                    path=matched,
                    state=str(row["state"]),
                    detail=f"path claim {row['id']} wins over claim-less work",
                )
            )
    return blockers


def git_touched_paths(worktree_path: str, integration_target: str) -> list[str]:
    """Return changed paths from a live worktree when git can read it."""
    if not worktree_path:
        return []
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                worktree_path,
                "diff",
                "--name-only",
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
    ignore_frozen_planning_scopes: bool,
) -> list[ConflictMatch]:
    marker = _p(conn)
    worktree_select = (
        ", iw.path AS worktree_path, iw.branch AS worktree_branch"
        if _table_exists(conn, "item_worktrees")
        else ", NULL AS worktree_path, NULL AS worktree_branch"
    )
    worktree_join = (
        " LEFT JOIN item_worktrees iw ON iw.item_id = i.id AND iw.state = 'active'"
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
        if all(
            _table_exists(conn, table)
            for table in ("item_strategy_docs", "strategy_docs")
        )
        else ", '' AS execution_document"
    )
    doc_join = (
        " LEFT JOIN item_strategy_docs isl ON isl.item_id = i.id "
        "LEFT JOIN strategy_docs sd ON sd.project_id = isl.project_id "
        "AND sd.slug = isl.strategy_doc_slug"
        if "sd.content" in doc_select
        else ""
    )
    rows = _dict_rows(
        conn.execute(
            "SELECT i.id, i.status, COALESCE(i.frozen, 0) AS frozen, "
            "COALESCE(i.spec, '') AS spec"
            f"{worktree_select}{claim_select}{doc_select} FROM items i"
            f"{worktree_join}{claim_join}{doc_join} "
            f"WHERE i.project_id = {marker} AND i.id <> {marker}",
            (int(item["project_id"]), int(item["id"])),
        )
    )
    blockers: list[ConflictMatch] = []
    seen: set[tuple[str, int, str]] = set()
    for row in rows:
        if str(row["status"]) in _TERMINAL_STATUSES:
            continue
        if (
            ignore_frozen_planning_scopes
            and bool(row.get("frozen"))
            and row.get("work_claim_id") is None
            and not row.get("worktree_path")
        ):
            continue
        declared = extract_file_budget_paths(
            f"{row['spec']}\n{row['execution_document']}"
        )
        worktree_paths = git_touched_paths(
            str(row.get("worktree_path") or ""), integration_target
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
            blockers.append(
                ConflictMatch(
                    kind=kind,
                    owner_item_id=int(row["id"]),
                    path=matched,
                    state=state,
                    detail=detail,
                )
            )
            seen.add(key)
    return blockers


def direct_workflow_blockers(
    conn: Any,
    *,
    item: dict[str, Any],
    touch_paths: tuple[str, ...],
    integration_target: str,
) -> list[ConflictMatch]:
    """Return path-claim and work-item blockers for a direct-workflow item."""
    ignore_frozen_planning_scopes = _ignores_frozen_planning_scopes(conn, item)
    return [
        *_path_claim_blockers(
            conn,
            item=item,
            touch_paths=touch_paths,
            integration_target=integration_target,
            ignore_frozen_planning_scopes=ignore_frozen_planning_scopes,
        ),
        *_item_coordination_blockers(
            conn,
            item=item,
            touch_paths=touch_paths,
            integration_target=integration_target,
            ignore_frozen_planning_scopes=ignore_frozen_planning_scopes,
        ),
    ]
