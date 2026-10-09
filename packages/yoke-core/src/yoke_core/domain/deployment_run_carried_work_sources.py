"""Resolve deployment-range commits to backlog items from durable evidence.

Ownership is read only from records that bind an exact commit to its item —
the item's merge receipt first, whose contributed commits name every commit a
landing put on the target's first-parent line, then QA and execution evidence
and lane metadata. A commit message naming an item is not such a record: it
says what someone wrote about a commit, not who landed it, and crediting it
can hand an unrelated commit to whichever item it mentions. A commit nothing
binds is carried as a commit made outside Yoke, without blocking the release.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from yoke_contracts.public_ref import format_item_ref
from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain.dash_execution import DASH_EVIDENCE_SECTION
from yoke_core.domain.json_helper import loads_text
from yoke_core.domain.item_merge_receipt_document import merge_identities


LANDING_TIME_TOLERANCE_SECONDS = 600
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


def _safe_read(
    conn: Any,
    read: Any,
    *,
    reason: str,
    recovery: str,
    warnings: list[dict[str, str]],
) -> list[Any]:
    """Run one optional evidence read, warning instead of failing the run."""
    conn.execute("SAVEPOINT carried_work_optional_read")
    try:
        rows = list(read())
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


def _safe_rows(
    conn: Any,
    sql: str,
    params: Sequence[Any],
    *,
    reason: str,
    recovery: str,
    warnings: list[dict[str, str]],
) -> list[Any]:
    return _safe_read(
        conn,
        lambda: conn.execute(sql, tuple(params)).fetchall(),
        reason=reason,
        recovery=recovery,
        warnings=warnings,
    )


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


def _project_items(conn: Any, project_id: int) -> dict[int, str]:
    rows = conn.execute(
        "SELECT i.id,i.project_sequence,p.slug,p.public_item_prefix "
        "FROM items i JOIN projects p ON p.id=i.project_id "
        "WHERE i.project_id=%s",
        (project_id,),
    ).fetchall()
    return {
        int(_cell(row, "id", 0)): format_item_ref(
            str(_cell(row, "slug", 2)),
            str(_cell(row, "public_item_prefix", 3) or ""),
            int(_cell(row, "project_sequence", 1)),
        )
        for row in rows
    }


def _resolve_recorded_evidence(
    conn: Any,
    *,
    project_id: int,
    commits: Sequence[str],
    known_items: Mapping[int, str],
    resolved: dict[str, set[int]],
    warnings: list[dict[str, str]],
) -> None:
    """Attribute range commits from records that name the item outright.

    The item's merge receipt leads: it binds a merge, its implementation
    commit, and every commit the landing contributed to the item that
    produced them, and it outlives the branch and lane the merge removed.
    """
    for item_id, sha in _safe_read(
        conn,
        lambda: merge_identities(conn, project_id),
        reason="merge_receipts_unavailable",
        recovery="Restore item-section reads, then retry run completion.",
        warnings=warnings,
    ):
        _add_resolution(resolved, commits, sha, item_id, known_items)
    sources = (
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


def _commit_instant(value: Any) -> datetime | None:
    """Missing or invalid external commit evidence cannot identify a landing."""
    if value is None or value == "":
        return None
    try:
        return parse_instant(value)
    except InvalidInstant:
        return None


def _resolve_item_metadata(
    conn: Any,
    *,
    project_id: int,
    source: Any,
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
        commit: _commit_instant(source.commit_time(commit)) for commit in commits
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
        landed_at = _cell(row, "merge_queue_landed_at", 2) or _cell(row, "merged_at", 1)
        lane_commit = ""
        # A lane branch names its item's contribution only once the item has
        # landed: an open lane forked from the trunk points at somebody else's
        # commit until it has one of its own. The recorded lane head needs no
        # such proof — it is already the item's own commit.
        branch_token = [_cell(row, "branch", 4)] if landed_at else []
        for raw_token in (_cell(row, "commit_sha", 5), *branch_token):
            lane_token = str(raw_token or "").strip()
            if lane_token:
                lane_commit = source.resolve_commit(lane_token)
            if lane_commit:
                break
        if lane_commit:
            carrier = source.carrying_commit(
                lane_commit, base=base, head=head, commits=commits
            )
            if carrier:
                _add_resolution(resolved, commits, carrier, item_id, known_items)
        numeric_item_id = int(item_id)
        if any(numeric_item_id in item_ids for item_ids in resolved.values()):
            continue
        landed = parse_instant(landed_at) if landed_at is not None else None
        if landed is None:
            continue
        distances = sorted(
            (abs(when - landed), commit)
            for commit, when in commit_times.items()
            if when is not None
        )
        if distances:
            distance, commit = distances[0]
            unique_nearest = len(distances) == 1 or distance < distances[1][0]
            if unique_nearest and distance <= timedelta(
                seconds=LANDING_TIME_TOLERANCE_SECONDS
            ):
                _add_resolution(resolved, commits, commit, item_id, known_items)


def resolve_carried_items(
    conn: Any,
    *,
    project_id: int,
    source: Any,
    base: str,
    head: str,
    commits: Sequence[str],
) -> tuple[dict[int, str], dict[str, set[int]], list[dict[str, str]]]:
    """Return item labels, commit-to-item matches, and degraded-source notes."""
    known_items = _project_items(conn, project_id)
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
    _resolve_item_metadata(
        conn,
        project_id=project_id,
        source=source,
        base=base,
        head=head,
        commits=commits,
        known_items=known_items,
        resolved=resolved,
        warnings=warnings,
    )
    warnings.extend(source.warnings())
    return known_items, resolved, warnings


__all__ = ["LANDING_TIME_TOLERANCE_SECONDS", "resolve_carried_items"]
