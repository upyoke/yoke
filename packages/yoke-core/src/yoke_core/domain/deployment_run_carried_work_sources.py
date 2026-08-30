"""Resolve deployment-range commits to backlog items from durable evidence."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.dash_execution import DASH_EVIDENCE_SECTION
from yoke_core.domain.json_helper import loads_text
from yoke_core.domain.standalone_item_merge_receipt import RECEIPT_EVENT_NAME


LANDING_TIME_TOLERANCE_SECONDS = 600
_ITEM_REF = re.compile(r"\b[A-Z][A-Z0-9]*-[1-9][0-9]*\b")
_HEX_REF = re.compile(r"^[0-9a-fA-F]{7,64}$")


def _cell(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if value in (None, ""):
        return {}
    try:
        parsed = loads_text(str(value))
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _safe_rows(
    conn: Any,
    sql: str,
    params: Sequence[Any],
    *,
    reason: str,
    recovery: str,
    warnings: list[dict[str, str]],
) -> list[Any]:
    conn.execute("SAVEPOINT carried_work_optional_read")
    try:
        rows = list(conn.execute(sql, tuple(params)).fetchall())
    except Exception as exc:  # noqa: BLE001 - optional evidence source
        conn.execute("ROLLBACK TO SAVEPOINT carried_work_optional_read")
        conn.execute("RELEASE SAVEPOINT carried_work_optional_read")
        warnings.append(
            {
                "reason": reason,
                "recovery": recovery,
                "error_type": type(exc).__name__,
            }
        )
        return []
    conn.execute("RELEASE SAVEPOINT carried_work_optional_read")
    return rows


def _match_commit(value: Any, commits: Sequence[str]) -> str:
    candidate = str(value or "").strip().lower()
    if not candidate:
        return ""
    matches = [
        commit
        for commit in commits
        if commit.lower().startswith(candidate) or candidate.startswith(commit.lower())
    ]
    return matches[0] if len(matches) == 1 else ""


def _add_resolution(
    resolved: dict[str, set[int]],
    commits: Sequence[str],
    commit_value: Any,
    item_id: Any,
    known_items: Mapping[int, str],
) -> None:
    try:
        numeric_item_id = int(item_id)
    except (TypeError, ValueError):
        return
    commit = _match_commit(commit_value, commits)
    if commit and numeric_item_id in known_items:
        resolved.setdefault(commit, set()).add(numeric_item_id)


def _project_items(
    conn: Any,
    project_id: int,
) -> tuple[dict[int, str], dict[str, int]]:
    rows = conn.execute(
        "SELECT i.id,i.project_sequence,p.slug,p.public_item_prefix "
        "FROM items i JOIN projects p ON p.id=i.project_id "
        "WHERE i.project_id=%s",
        (project_id,),
    ).fetchall()
    refs: dict[int, str] = {}
    tokens: dict[str, int] = {}
    for row in rows:
        item_id = int(_cell(row, "id", 0))
        public_ref = format_item_ref(
            str(_cell(row, "slug", 2)),
            str(_cell(row, "public_item_prefix", 3) or ""),
            int(_cell(row, "project_sequence", 1)),
        )
        refs[item_id] = public_ref
        tokens[public_ref.upper()] = item_id
    return refs, tokens


def _resolve_recorded_evidence(
    conn: Any,
    *,
    project_id: int,
    commits: Sequence[str],
    known_items: Mapping[int, str],
    resolved: dict[str, set[int]],
    warnings: list[dict[str, str]],
) -> None:
    sources = (
        (
            "SELECT e.item_id,e.envelope FROM events e "
            "WHERE e.project_id=%s "
            "AND e.event_name=%s",
            (project_id, RECEIPT_EVENT_NAME),
            "merge_receipts_unavailable",
            "Restore events-ledger read authority, then retry run completion.",
            "envelope",
            ("context.merge_sha", "context.commit_sha"),
        ),
        (
            "SELECT qr.item_id,qrun.raw_result FROM qa_runs qrun "
            "JOIN qa_requirements qr ON qr.id=qrun.qa_requirement_id "
            "JOIN items i ON i.id=qr.item_id WHERE i.project_id=%s "
            "AND qrun.raw_result IS NOT NULL",
            (project_id,),
            "merge_queue_receipts_unavailable",
            "Restore QA receipt reads, then retry run completion.",
            "raw_result",
            ("merge_queue_batch.merge_sha",),
        ),
        (
            "SELECT s.item_id,s.content FROM item_sections s "
            "JOIN items i ON i.id=s.item_id WHERE i.project_id=%s "
            "AND s.section_name=%s",
            (project_id, DASH_EVIDENCE_SECTION),
            "item_merge_evidence_unavailable",
            "Restore item-section reads, then retry run completion.",
            "content",
            ("merge_sha",),
        ),
    )
    for sql, params, reason, recovery, value_key, paths in sources:
        rows = _safe_rows(
            conn,
            sql,
            params,
            reason=reason,
            recovery=recovery,
            warnings=warnings,
        )
        for row in rows:
            body = _object(_cell(row, value_key, 1))
            for path in paths:
                value: Any = body
                for key in path.split("."):
                    value = value.get(key) if isinstance(value, Mapping) else None
                _add_resolution(
                    resolved,
                    commits,
                    value,
                    _cell(row, "item_id", 0),
                    known_items,
                )


def _parse_time(value: Any) -> datetime | None:
    token = str(value or "").strip()
    if not token:
        return None
    try:
        parsed = datetime.fromisoformat(token.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _resolve_item_metadata(
    conn: Any,
    *,
    project_id: int,
    repo_root: str,
    base: str,
    head: str,
    commits: Sequence[str],
    known_items: Mapping[int, str],
    resolved: dict[str, set[int]],
    warnings: list[dict[str, str]],
) -> None:
    rows = _safe_rows(
        conn,
        "SELECT i.id,i.merged_at,i.merge_queue_landed_at,i.resolution_ref,"
        "iw.branch,iw.commit_sha FROM items i LEFT JOIN item_worktrees iw "
        "ON iw.item_id=i.id WHERE i.project_id=%s AND (i.merged_at IS NOT NULL "
        "OR i.merge_queue_landed_at IS NOT NULL OR i.resolution_ref IS NOT NULL "
        "OR iw.commit_sha IS NOT NULL)",
        (project_id,),
        reason="item_merge_metadata_unavailable",
        recovery="Restore item and lane metadata reads, then retry run completion.",
        warnings=warnings,
    )
    commit_times = {
        commit: _parse_time(
            git.git_out(repo_root, "show", "-s", "--format=%cI", commit)
        )
        for commit in commits
    }
    for row in rows:
        item_id = _cell(row, "id", 0)
        resolution_ref = str(_cell(row, "resolution_ref", 3) or "").strip()
        if _HEX_REF.fullmatch(resolution_ref):
            _add_resolution(
                resolved,
                commits,
                resolution_ref,
                item_id,
                known_items,
            )
        lane_commit = ""
        for raw_token in (_cell(row, "commit_sha", 5), _cell(row, "branch", 4)):
            lane_token = str(raw_token or "").strip()
            if lane_token:
                lane_commit = git.git_out(
                    repo_root,
                    "rev-parse",
                    "--verify",
                    f"{lane_token}^{{commit}}",
                )
            if lane_commit:
                break
        if lane_commit and not git.is_ancestor(repo_root, lane_commit, base):
            if git.is_ancestor(repo_root, lane_commit, head):
                for commit in commits:
                    if git.is_ancestor(repo_root, lane_commit, commit):
                        _add_resolution(
                            resolved,
                            commits,
                            commit,
                            item_id,
                            known_items,
                        )
                        break
        numeric_item_id = int(item_id)
        if any(numeric_item_id in item_ids for item_ids in resolved.values()):
            continue
        landed = _parse_time(
            _cell(row, "merge_queue_landed_at", 2) or _cell(row, "merged_at", 1)
        )
        if landed is None:
            continue
        distances = sorted(
            (abs((when - landed).total_seconds()), commit)
            for commit, when in commit_times.items()
            if when is not None
        )
        if distances:
            distance, commit = distances[0]
            unique_nearest = len(distances) == 1 or distance < distances[1][0]
            if unique_nearest and distance <= LANDING_TIME_TOLERANCE_SECONDS:
                _add_resolution(resolved, commits, commit, item_id, known_items)


def resolve_carried_items(
    conn: Any,
    *,
    project_id: int,
    repo_root: str,
    base: str,
    head: str,
    commits: Sequence[str],
) -> tuple[dict[int, str], dict[str, set[int]], list[dict[str, str]]]:
    """Return item labels, commit-to-item matches, and degraded-source notes."""
    known_items, item_tokens = _project_items(conn, project_id)
    resolved: dict[str, set[int]] = {}
    warnings: list[dict[str, str]] = []
    _resolve_recorded_evidence(
        conn,
        project_id=project_id,
        commits=commits,
        known_items=known_items,
        resolved=resolved,
        warnings=warnings,
    )
    for commit in commits:
        source = git.git_out(
            repo_root,
            "show",
            "-s",
            "--format=%B%n%D",
            commit,
        )
        for token in _ITEM_REF.findall(source.upper()):
            if token in item_tokens:
                resolved.setdefault(commit, set()).add(item_tokens[token])
    _resolve_item_metadata(
        conn,
        project_id=project_id,
        repo_root=repo_root,
        base=base,
        head=head,
        commits=commits,
        known_items=known_items,
        resolved=resolved,
        warnings=warnings,
    )
    return known_items, resolved, warnings


__all__ = ["LANDING_TIME_TOLERANCE_SECONDS", "resolve_carried_items"]
