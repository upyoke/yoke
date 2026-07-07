"""Ambient sibling-claim view rendered into session orientation.

Read-only query: given the current session's ``integration_target``,
return non-terminal sibling claims (other items' claims on the same
target). Each row carries:

* ``claim_id``
* ``item_id`` + item title (from ``items.title``)
* ``state`` (one of ``planned`` / ``blocked`` / ``active``)
* ``coverage_paths`` — top three coverage roots plus an additional-roots
  count (``extra_count``) so the render never overflows 80 columns.
* ``base_commit_age_hint`` — relative age of the claim's
  ``base_commit_sha`` against the current integration-target HEAD as a
  one-word hint (``current``, ``recent``, ``stale``, ``unknown``).

Per the resolved decisions, planned-future claims (no active or
non-terminal state) are filtered out — only ``planned`` / ``blocked``
/ ``active`` show up. The render keeps each line under 80 columns
(per Resolved Decisions) by truncating coverage and ellipsizing item
titles when they exceed the budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.path_claim_ambient_siblings_head_resolve import (
    resolve_integration_head_sha as _resolve_integration_head_sha,
)


_LINE_BUDGET = 78  # 80-column display, allow 2 chars trailing safety
_TOP_PATHS = 3
_NON_TERMINAL_STATES = ("active", "planned", "blocked")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@dataclass
class AmbientSiblingRow:
    """One sibling claim row consumed by the orientation renderer."""

    claim_id: int
    item_id: Optional[int]
    item_title: str
    state: str
    coverage_paths: List[str] = field(default_factory=list)
    extra_count: int = 0
    base_commit_age_hint: str = "unknown"


def fetch_rows(
    *,
    integration_target: str,
    exclude_claim_id: Optional[int] = None,
    conn: Optional[Any] = None,
) -> List[AmbientSiblingRow]:
    """Return non-terminal sibling claims on ``integration_target``.

    ``exclude_claim_id`` drops the current session's own claim from the
    sibling list (the orientation block already shows the active
    claim's own context elsewhere).

    Pass ``conn`` to inject a test fixture; defaults to opening a
    read-only connection via ``db_helpers``.
    """
    if not integration_target:
        return []

    own_conn = False
    if conn is None:
        try:
            from yoke_core.domain import db_helpers
        except ImportError:
            return []
        try:
            conn = db_helpers.connect()
            own_conn = True
        except Exception:
            return []

    try:
        return _fetch_rows(
            conn,
            integration_target=integration_target,
            exclude_claim_id=exclude_claim_id,
        )
    finally:
        if own_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _fetch_rows(
    conn: Any,
    *,
    integration_target: str,
    exclude_claim_id: Optional[int],
) -> List[AmbientSiblingRow]:
    p = _p(conn)
    placeholders = ",".join(p for _ in _NON_TERMINAL_STATES)
    args: list = [integration_target, *_NON_TERMINAL_STATES]
    extra_clause = ""
    if exclude_claim_id is not None:
        extra_clause = f"AND pc.id <> {p} "
        args.append(int(exclude_claim_id))
    try:
        rows = conn.execute(
            "SELECT pc.id, pc.item_id, pc.state, pc.base_commit_sha, "
            "       pc.activated_at, "
            "       COALESCE(i.title, '') AS title "
            "FROM path_claims pc "
            "LEFT JOIN items i ON i.id = pc.item_id "
            f"WHERE pc.integration_target = {p} "
            f"AND pc.state IN ({placeholders}) "
            f"{extra_clause}"
            "ORDER BY pc.id",
            tuple(args),
        ).fetchall()
    except db_backend.database_error_types(conn):
        return []

    # Resolve the integration head once per batch — every row in this
    # query shares the same target, so a single git rev-parse keeps the
    # render cheap.
    head_sha = _resolve_integration_head_sha(conn, integration_target)

    out: List[AmbientSiblingRow] = []
    for row in rows:
        claim_id = int(row[0] if not hasattr(row, "keys") else row["id"])
        item_id_raw = row[1] if not hasattr(row, "keys") else row["item_id"]
        state = str(row[2] if not hasattr(row, "keys") else row["state"])
        base_commit_sha_raw = (
            row[3] if not hasattr(row, "keys") else row["base_commit_sha"]
        )
        activated_at = row[4] if not hasattr(row, "keys") else row["activated_at"]
        title = str(row[5] if not hasattr(row, "keys") else row["title"])

        coverage = _coverage_for_claim(conn, claim_id)
        top, extra = _split_top_extra(coverage, _TOP_PATHS)
        age_hint = _age_hint_for_commit_sha(
            base_commit_sha=(
                str(base_commit_sha_raw) if base_commit_sha_raw else None
            ),
            integration_head_sha=head_sha,
            activated_at=str(activated_at) if activated_at else None,
        )

        out.append(
            AmbientSiblingRow(
                claim_id=claim_id,
                item_id=_coerce_int(item_id_raw),
                item_title=title,
                state=state,
                coverage_paths=top,
                extra_count=extra,
                base_commit_age_hint=age_hint,
            )
        )
    return out


def _coverage_for_claim(
    conn: Any, claim_id: int
) -> List[str]:
    try:
        p = _p(conn)
        rows = conn.execute(
            "SELECT pt.path_string FROM path_claim_targets pct "
            "JOIN path_targets pt ON pt.id = pct.target_id "
            f"WHERE pct.claim_id = {p} "
            "ORDER BY pct.id",
            (claim_id,),
        ).fetchall()
    except db_backend.database_error_types(conn):
        return []
    return [str(r[0]) for r in rows]


def _split_top_extra(
    paths: Sequence[str], top: int
) -> Tuple[List[str], int]:
    if not paths:
        return [], 0
    if len(paths) <= top:
        return list(paths), 0
    return list(paths[:top]), len(paths) - top


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _age_hint_for_commit_sha(
    *,
    base_commit_sha: Optional[str],
    integration_head_sha: Optional[str],
    activated_at: Optional[str],
) -> str:
    """Return a one-word hint for the claim's base commit age vs HEAD.

    The orientation render is informative, not authoritative — we use a
    coarse bucket (``current`` / ``recent`` / ``stale`` / ``unknown``)
    so the line stays compact. ``current`` means the claim's recorded
    base SHA matches the integration target's current head; ``recent``
    means activated within 24h; ``stale`` means older; ``unknown``
    covers any data miss.
    """
    if not base_commit_sha:
        return "unknown"
    if integration_head_sha and integration_head_sha == base_commit_sha:
        return "current"
    if not activated_at:
        return "unknown"
    age_hours = _age_hours(activated_at)
    if age_hours is None:
        return "unknown"
    if age_hours <= 24:
        return "recent"
    return "stale"


def _age_hours(timestamp: str) -> Optional[float]:
    try:
        ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - ts
    return delta.total_seconds() / 3600.0


def render(
    integration_target: str,
    *,
    exclude_claim_id: Optional[int] = None,
    conn: Optional[Any] = None,
) -> str:
    """Render the ambient sibling-claims block for orientation.

    Returns a multi-line string fitting an 80-column display, or an
    empty string when no sibling claims exist (the caller can skip the
    section header in that case).
    """
    rows = fetch_rows(
        integration_target=integration_target,
        exclude_claim_id=exclude_claim_id,
        conn=conn,
    )
    if not rows:
        return ""

    lines: List[str] = [
        f"### Sibling Path Claims ({integration_target})",
        "",
        "```",
    ]
    for row in rows:
        lines.extend(_format_row(row))
    lines.append("```")
    return "\n".join(lines)


def _format_row(row: AmbientSiblingRow) -> List[str]:
    """Format one sibling row into 1-2 lines fitting 80 columns."""
    item_label = (
        f"YOK-{row.item_id}" if row.item_id is not None else "YOK-?"
    )
    head = f"claim {row.claim_id:<5} [{row.state:<7}] {item_label}"
    title = (row.item_title or "").strip()
    title_room = _LINE_BUDGET - len(head) - len(" — ") - len(
        f" ({row.base_commit_age_hint})"
    )
    if title_room < 8:
        title_room = 8
    if len(title) > title_room:
        title = title[: title_room - 1] + "…"
    head_line = (
        f"{head} — {title} ({row.base_commit_age_hint})"
        if title
        else f"{head} ({row.base_commit_age_hint})"
    )

    coverage_str = _format_coverage(
        row.coverage_paths, row.extra_count, indent="    "
    )
    return [head_line, coverage_str]


def _format_coverage(paths: Sequence[str], extra: int, *, indent: str) -> str:
    if not paths:
        return f"{indent}(no declared coverage)"
    rendered = ", ".join(paths)
    if extra:
        rendered = f"{rendered} +{extra} more"
    line = f"{indent}{rendered}"
    if len(line) > _LINE_BUDGET:
        # Trim path list further until the line fits.
        budget = _LINE_BUDGET - len(indent) - len(" …")
        if budget < 16:
            budget = 16
        line = f"{indent}{rendered[:budget]}…"
    return line


__all__ = [
    "AmbientSiblingRow",
    "fetch_rows",
    "render",
]
