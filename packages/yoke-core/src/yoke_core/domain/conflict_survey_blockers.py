"""Blocker discovery for direct-workflow conflict surveys."""

from __future__ import annotations

import subprocess
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.conflict_survey_declared_paths import (
    CONFLICT_SURVEY_SECTION,
    declared_surveys,
    matching_scope,
)
from yoke_core.domain.conflict_survey_models import ConflictMatch
from yoke_core.domain.file_budget_paths import (
    extract_file_budget_paths,
    extract_file_budget_section_paths,
)
from yoke_core.domain.file_budget_paths import FILE_BUDGET_SECTION
from yoke_core.domain.path_render_overlap import is_render_target_only_overlap
from yoke_core.domain.schema_common import _table_exists

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


def _matching_reportable_scope(
    conn: Any,
    *,
    touch_paths: tuple[str, ...],
    other_paths: list[str] | tuple[str, ...],
    project_id: int,
) -> str:
    matched = matching_scope(touch_paths, other_paths)
    if matched and is_render_target_only_overlap(
        conn,
        candidate_paths=touch_paths,
        other_paths=other_paths,
        project_id=project_id,
    ):
        return ""
    return matched


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
    claims: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        claims.setdefault(int(row["id"]), []).append(row)
    for claim_rows in claims.values():
        row = claim_rows[0]
        owner = row.get("owner_item_id")
        if owner is not None and int(owner) == int(item["id"]):
            continue
        if bool(row.get("owner_frozen")):
            continue
        claim_paths = [str(entry["path_string"]) for entry in claim_rows]
        if is_render_target_only_overlap(
            conn,
            candidate_paths=touch_paths,
            other_paths=claim_paths,
            project_id=int(item["project_id"]),
        ):
            continue
        for entry in claim_rows:
            matched = matching_scope(touch_paths, [str(entry["path_string"])])
            if matched:
                blockers.append(
                    ConflictMatch(
                        kind="path_claim",
                        owner_item_id=int(owner) if owner is not None else None,
                        path=matched,
                        state=str(entry["state"]),
                        detail=f"uncoordinated path claim {entry['id']}",
                    )
                )
    return blockers


def _git_lines(worktree_path: str, argv: list[str]) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", worktree_path, *argv],
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


def git_touched_paths(worktree_path: str, integration_target: str) -> list[str]:
    """Return changed paths from a live worktree when git can read it.

    Three reads, because committed history alone hides an agent that is
    mid-edit: the branch's own commits against the integration target,
    tracked edits not yet committed, and files git is not tracking yet.
    Ignored files stay out, so lane scratch never reads as declared work.
    """
    if not worktree_path:
        return []
    touched: list[str] = []
    for argv in (
        ["diff", "--name-only", f"{integration_target}...HEAD"],
        ["diff", "--name-only", "HEAD"],
        ["ls-files", "--others", "--exclude-standard"],
    ):
        touched.extend(_git_lines(worktree_path, argv))
    return list(dict.fromkeys(touched))


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
    # A File Budget authored through the section surface never reaches
    # ``items.spec``, so reading the spec alone misses it entirely. Both
    # storages are live, so both are read.
    budget_select = (
        ", COALESCE(fb.content, '') AS file_budget_section"
        if _table_exists(conn, "item_sections")
        else ", '' AS file_budget_section"
    )
    budget_join = (
        " LEFT JOIN item_sections fb ON fb.item_id = i.id "
        f"AND fb.section_name = {marker}"
        if _table_exists(conn, "item_sections")
        else ""
    )
    params: list[Any] = []
    if budget_join:
        params.append(FILE_BUDGET_SECTION)
    params.extend([int(item["project_id"]), int(item["id"])])
    rows = _dict_rows(
        conn.execute(
            "SELECT i.id, i.status, COALESCE(i.frozen, 0) AS frozen, "
            "COALESCE(i.spec, '') AS spec"
            f"{worktree_select}{claim_select}{doc_select}{budget_select}"
            f" FROM items i"
            f"{worktree_join}{claim_join}{doc_join}{budget_join} "
            f"WHERE i.project_id = {marker} AND i.id <> {marker}",
            tuple(params),
        )
    )
    surveys = {
        survey.item_id: survey.paths
        for survey in declared_surveys(
            conn,
            project_id=int(item["project_id"]),
            integration_target=integration_target,
            exclude_item_id=int(item["id"]),
        )
    }
    blockers: list[ConflictMatch] = []
    seen: set[tuple[str, int, str]] = set()
    for row in rows:
        if str(row["status"]) in _TERMINAL_STATUSES:
            continue
        if bool(row.get("frozen")):
            continue
        declared = [
            *extract_file_budget_paths(f"{row['spec']}\n{row['execution_document']}"),
            *extract_file_budget_section_paths(
                str(row.get("file_budget_section") or "")
            ),
        ]
        worktree_paths = git_touched_paths(
            str(row.get("worktree_path") or ""), integration_target
        )
        active_paths = [*worktree_paths, *declared]
        matched = _matching_reportable_scope(
            conn,
            touch_paths=touch_paths,
            other_paths=active_paths,
            project_id=int(item["project_id"]),
        )
        # A recorded survey is the weakest of the three signals — declared
        # intent, not work already under way — so it answers only where the
        # stronger ones found nothing, and it is attributed separately so
        # the operator can tell the two apart.
        survey_paths = surveys.get(int(row["id"]), ())
        survey_match = (
            ""
            if matched
            else _matching_reportable_scope(
                conn,
                touch_paths=touch_paths,
                other_paths=survey_paths,
                project_id=int(item["project_id"]),
            )
        )
        if not matched and not survey_match:
            continue
        if not matched:
            matched = survey_match
            kind, state = "survey_scope", str(row["status"])
            detail = (
                "non-terminal item declares this path in its recorded "
                f"{CONFLICT_SURVEY_SECTION}"
            )
        elif row.get("work_claim_id") is not None:
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
    return [
        *_path_claim_blockers(
            conn,
            item=item,
            touch_paths=touch_paths,
            integration_target=integration_target,
        ),
        *_item_coordination_blockers(
            conn,
            item=item,
            touch_paths=touch_paths,
            integration_target=integration_target,
        ),
    ]
