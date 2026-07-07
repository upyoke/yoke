"""GitHub body-size budget guard + compact-mirror renderer.

GitHub caps issue bodies at 65,536 characters. When the Yoke-rendered
body exceeds this, the REST issue-edit endpoint rejects the call with
a body-too-long GraphQL error and the sync silently fails.

This module owns the pre-call check and the compact-mirror fallback:

- :data:`GITHUB_BODY_BUDGET_BYTES` (62000) is the byte-length ceiling. The
  small headroom below GitHub's character ceiling absorbs multi-byte UTF-8
  expansion and GraphQL request-envelope overhead.
- :func:`body_exceeds_budget` is a pure byte-length predicate.
- :func:`render_compact_mirror` renders a small, GitHub-side breadcrumb
  pointing at the canonical Yoke DB.
- :func:`select_body_for_github` is the single decision point: returns
  ``(body, "full")`` when under budget, ``(mirror, "compact")`` otherwise.
- :func:`select_and_write_body_file` is the shared "select + write to a
  named temp file" helper that ``sync_body`` and the create path in
  ``backlog_github_item_create`` both call.

The body-size check is byte-length, not char-length. A 31k-char emoji
body is ~124k bytes; ``len(body) > 62000`` would falsely pass it.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Literal, Optional, TextIO

from yoke_core.domain.project_identity import DEFAULT_PUBLIC_ITEM_PREFIX, render_item_ref
from yoke_core.domain.project_scratch_dir import ephemeral_payload

GITHUB_BODY_BUDGET_BYTES: int = 62000

SyncMode = Literal["full", "compact"]

_TITLE_TRUNCATE_CHARS = 500


def body_exceeds_budget(body: str) -> bool:
    """Return ``True`` when ``body`` byte-length exceeds the budget."""
    return len(body.encode("utf-8")) > GITHUB_BODY_BUDGET_BYTES


# ---------------------------------------------------------------------------
# Compact-mirror renderer
# ---------------------------------------------------------------------------


_COMMANDS_BY_LIFECYCLE: dict[str, list[str]] = {
    "idea": [
        "`/yoke refine {id}` — turn the idea into a refined spec.",
    ],
    "refining-idea": [
        "`/yoke refine {id}` — continue refining the spec.",
    ],
    "refined-idea": [
        "`/yoke advance {id} implementation` — start an implementation lane.",
    ],
    "implementing": [
        "`/yoke advance {id} reviewing-implementation` — open review loop.",
    ],
    "reviewing-implementation": [
        "`/yoke advance {id} reviewed-implementation` — close review loop.",
    ],
    "reviewed-implementation": [
        "`/yoke polish {id}` — final polish pass before merge.",
    ],
    "polishing-implementation": [
        "`/yoke polish {id}` — continue polishing.",
    ],
    "implemented": [
        "`/yoke usher {id}` — merge and deploy.",
    ],
    "planning": [
        "`/yoke shepherd {id}` — author the epic plan.",
    ],
    "plan-drafted": [
        "`/yoke refine {id}` — refine the plan tasks.",
    ],
    "refining-plan": [
        "`/yoke refine {id}` — finish refining the plan.",
    ],
    "planned": [
        "`/yoke conduct {id}` — kick off epic execution.",
    ],
}


def _truncate(text: str, limit: int = _TITLE_TRUNCATE_CHARS) -> str:
    """Truncate ``text`` to ``limit`` chars with an ellipsis suffix."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _display_ref(item_ref: int | str) -> str:
    text = str(item_ref).strip()
    if text.isdigit():
        return f"{DEFAULT_PUBLIC_ITEM_PREFIX}-{text}"
    return text or f"{DEFAULT_PUBLIC_ITEM_PREFIX}-0"


def _public_ref(conn: Optional[Any], item_id: int) -> str:
    if conn is None:
        return _display_ref(item_id)
    try:
        return render_item_ref(conn, item_id)
    except Exception:
        return _display_ref(item_id)


def _evidence_summary(
    conn: Optional[Any],
    item_id: int,
) -> str:
    """Render the item's latest status transition as one evidence line.

    Best-effort: on any read failure, return ``"no recent evidence"`` rather
    than failing the whole sync.
    """
    if conn is None:
        return "no recent evidence"
    from yoke_core.domain.item_status_transitions import latest_transition

    row = latest_transition(conn, item_id)
    if row is None:
        return "no recent evidence"
    task_part = (
        f" (task {row['task_num']})" if row.get("task_num") is not None else ""
    )
    return (
        f"latest transition: {row.get('from_status') or '?'} -> "
        f"{row['to_status']}{task_part} at {row['created_at']}"
    )


def _lifecycle_commands(status: str, item_ref: str) -> list[str]:
    template = _COMMANDS_BY_LIFECYCLE.get(status)
    if not template:
        return [f"`/yoke do {item_ref}` — pick the next available action."]
    return [line.format(id=item_ref) for line in template]


def render_compact_mirror(
    item_fields: dict,
    *,
    conn: Optional[Any],
    item_id: int,
) -> str:
    """Render the GitHub compact-mirror body.

    The mirror must itself fit under :data:`GITHUB_BODY_BUDGET_BYTES`; the
    title is truncated and the evidence summary is a single line.
    """
    title = _truncate(str(item_fields.get("title") or ""))
    project = str(item_fields.get("project") or "")
    status = str(item_fields.get("status") or "")
    item_type = str(item_fields.get("type") or "")
    lifecycle = status or "unknown"
    subject_ref = _display_ref(item_fields.get("identity") or _public_ref(conn, item_id))
    body_command = str(
        item_fields.get("body_command")
        or f"python3 -m yoke_core.cli.db_router items get {subject_ref} body"
    )

    body_lines: list[str] = []
    body_lines.append(f"# [{subject_ref}] {title}".rstrip())
    body_lines.append("")
    body_lines.append(
        "Full body lives in the Yoke DB — "
        f"`{body_command}`"
    )
    body_lines.append("")
    body_lines.append("## Identity")
    body_lines.append(f"- **Reference:** {subject_ref}")
    if project:
        body_lines.append(f"- **Project:** {project}")
    if item_type:
        body_lines.append(f"- **Type:** {item_type}")
    body_lines.append(f"- **Status:** {status or '(unset)'}")
    body_lines.append(f"- **Lifecycle:** {lifecycle}")
    body_lines.append("")
    body_lines.append("## Next actions")
    configured_actions = item_fields.get("next_actions")
    if isinstance(configured_actions, (list, tuple)) and configured_actions:
        action_lines = [str(line) for line in configured_actions if str(line).strip()]
    else:
        action_lines = _lifecycle_commands(lifecycle, subject_ref)
    for line in action_lines:
        body_lines.append(f"- {line}")
    body_lines.append("")
    body_lines.append("## Evidence")
    body_lines.append(f"- {_evidence_summary(conn, item_id)}")
    body_lines.append("")
    body_lines.append(
        "_Body exceeded GitHub's size budget; full content stays in the DB._"
    )

    return "\n".join(body_lines) + "\n"


# ---------------------------------------------------------------------------
# Body selector + shared temp-file writer
# ---------------------------------------------------------------------------


def select_body_for_github(
    full_body: str,
    *,
    item_fields: dict,
    conn: Optional[Any],
    item_id: int,
) -> tuple[str, SyncMode]:
    """Pick the body that will actually go to GitHub.

    Returns ``(full_body, "full")`` when under budget, otherwise
    ``(render_compact_mirror(...), "compact")``.
    """
    if not body_exceeds_budget(full_body):
        return full_body, "full"
    return (
        render_compact_mirror(item_fields, conn=conn, item_id=item_id),
        "compact",
    )


def select_and_write_body_file(
    full_body: str,
    *,
    item_fields: dict,
    conn: Optional[Any],
    item_id: int,
    prefix: str,
) -> tuple[str, SyncMode]:
    """Select + persist the GitHub body to a uniquely-named temp file.

    Returns ``(path, mode)``. The caller owns the file and must unlink it.
    Used by both ``sync_body`` and the create path in
    ``backlog_github_item_create`` so the body-budget decision happens at
    one shared call site.
    """
    body, mode = select_body_for_github(
        full_body, item_fields=item_fields, conn=conn, item_id=item_id,
    )
    # delete=False because the caller owns the file lifetime and unlinks
    # via :func:`unlink_quiet` after gh consumes ``--body-file``.
    with ephemeral_payload(
        prefix=prefix.rstrip("."),
        suffix=".md",
        delete=False,
    ) as body_path:
        body_path.write_text(body)
    return str(body_path), mode


def emit_compact_notice(
    mode: SyncMode,
    item_id: int | str,
    out: TextIO = sys.stderr,
) -> None:
    """Write a one-line notice to ``out`` when ``mode == "compact"``."""
    if mode == "compact":
        print(
            f"Note: {_display_ref(item_id)} body exceeded GitHub budget; "
            "synced compact mirror instead.",
            file=out,
        )


def unlink_quiet(path: str) -> None:
    """Best-effort unlink; ignores missing files."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


# Compact-pending flag — items.github_body_compact_pending: non-NULL ISO
# timestamp = the item's last successful body sync landed the compact
# mirror. Set by a compact sync, cleared by a full-body sync; the repair
# pass (`backfill-oversized-bodies`) reads it as its candidate queue
# (retired pattern: scanning telemetry envelopes for failure markers).


def record_sync_mode(conn: Optional[Any], item_id: int, mode: SyncMode) -> None:
    """Stamp/clear ``github_body_compact_pending`` after a successful sync.

    Best-effort: minimal fixture DBs without the column are tolerated
    (savepoint keeps the caller's transaction clean). Commits via the
    caller's connection.
    """
    if conn is None:
        return
    from yoke_core.domain import db_backend
    from yoke_core.domain.db_helpers import iso8601_now

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    value = iso8601_now() if mode == "compact" else None
    try:
        conn.execute("SAVEPOINT github_body_compact_pending")
        conn.execute(
            f"UPDATE items SET github_body_compact_pending = {p} "
            f"WHERE id = {p}",
            (value, int(item_id)),
        )
        conn.execute("RELEASE SAVEPOINT github_body_compact_pending")
        conn.commit()
    except Exception:
        try:
            conn.execute("ROLLBACK TO SAVEPOINT github_body_compact_pending")
            conn.execute("RELEASE SAVEPOINT github_body_compact_pending")
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass


def list_compact_pending_item_ids(conn: Any) -> list[int]:
    """GitHub-linked items whose mirror is currently the compact fallback."""
    try:
        rows = conn.execute(
            "SELECT id FROM items "
            "WHERE github_body_compact_pending IS NOT NULL "
            "AND github_issue IS NOT NULL AND github_issue <> '' "
            "ORDER BY id"
        ).fetchall()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return []
    return [int(r[0]) for r in rows]


__all__ = [
    "GITHUB_BODY_BUDGET_BYTES",
    "SyncMode",
    "body_exceeds_budget",
    "list_compact_pending_item_ids",
    "record_sync_mode",
    "render_compact_mirror",
    "select_body_for_github",
    "select_and_write_body_file",
    "emit_compact_notice",
    "unlink_quiet",
]
