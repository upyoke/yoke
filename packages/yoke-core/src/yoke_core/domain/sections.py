"""Python owner for ``item_sections`` CRUD.

Implements the ``sections`` domain (``upsert``, ``get``, ``list``, ``delete``),
invoked via ``python3 -m yoke_core.cli.db_router sections`` or
directly as ``python3 -m yoke_core.domain.sections``.

Preserved surface contract:

``upsert``
    Writes/updates a row in ``item_sections`` via
    ``ON CONFLICT(item_id, section_name)``. Triggers a body re-render for the
    parent item and emits a structured ``SectionUpserted`` event. Maintains
    the stable stdout ("Upserted section: {name} for item {id}", then "Body
    regenerated for item {id}") and stderr ("Error: body regeneration
    failed…") lines for downstream callers that inspect command output.

``get``
    Returns the raw ``content`` column verbatim. Missing rows print nothing;
    present rows print ``content`` followed by a trailing newline to match
    the shell's ``sqlite3`` output.

``list``
    Prints one pipe-delimited line per row:
    ``name|ordering|created_at|updated_at``, ordered by
    ``COALESCE(ordering, 999999), section_name``.

``delete``
    Deletes the row, triggers body re-render, emits a ``SectionDeleted``
    event. Output mirrors the shell: "Deleted section: {name} for item
    {id}" followed by the re-render success/failure line.

The renderer and event emitter are injectable so tests can stub them
without touching the real pipelines. The rest of the module uses
``yoke_core.domain.db_helpers`` for connection management.
"""

from __future__ import annotations

import sys
from io import StringIO
from typing import Callable, List, Optional, TextIO, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain import db_helpers
from yoke_core.domain.db_helpers import BUSY_TIMEOUT_MS
from yoke_core.domain.events import emit_event as _default_emit_event
from yoke_core.domain.render_body import render_item as _default_render_item

RendererFn = Callable[..., int]
EmitEventFn = Callable[..., Optional[dict]]

_render_fn: RendererFn = _default_render_item
_emit_event_fn: EmitEventFn = _default_emit_event
SECTION_SYNC_GITHUB_TIMEOUT_SECONDS = 5.0
SECTION_SYNC_GITHUB_MAX_ATTEMPTS = 1


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


# ---------------------------------------------------------------------------
# Dependency injection hooks (tests only)
# ---------------------------------------------------------------------------


def set_renderer(fn: Optional[RendererFn]) -> None:
    """Override the body renderer. Pass ``None`` to reset to default."""
    global _render_fn
    _render_fn = fn if fn is not None else _default_render_item


def set_event_emitter(fn: Optional[EmitEventFn]) -> None:
    """Override the event emitter. Pass ``None`` to reset to default."""
    global _emit_event_fn
    _emit_event_fn = fn if fn is not None else _default_emit_event


def _rerender_body(
    item_id: int,
    action: str,
    db_path: Optional[str],
    out: TextIO,
    err: TextIO,
) -> bool:
    """Re-render the item body via the in-process render owner.

    Returns ``True`` on success (emits "Body regenerated…" to *out*);
    returns ``False`` on failure (emits the failure line to *err*). The
    Body rendering is owned by ``yoke_core.domain.render_body.render_item``.
    """
    sink = StringIO()
    err_sink = StringIO()
    try:
        rc = _render_fn(item_id, db_path=db_path, out=sink, err=err_sink)
    except TypeError:
        # Allow test stubs with a simpler signature.
        try:
            rc = _render_fn(item_id)
        except Exception:
            rc = 1
    except Exception:
        rc = 1
    if rc == 0:
        print("Body regenerated for item {}".format(item_id), file=out)
        return True
    print(
        "Error: body regeneration failed for item {} after section {}; "
        "section mutation was written but body is stale. Skipping GitHub sync.".format(
            item_id, action
        ),
        file=err,
    )
    return False


def _emit_section_event(event_name: str, item_id: int, section_name: str) -> None:
    """Best-effort structured event emission for section mutations."""
    try:
        _emit_event_fn(
            event_name,
            event_kind="system",
            event_type="data_mutation",
            source_type="script",
            severity="INFO",
            outcome="completed",
            item_id=str(item_id),
            context={"item_id": str(item_id), "section": section_name},
        )
    except Exception:
        # Event failures must not abort the section mutation.
        pass


def sync_body_after_section_mutation(
    item_id: int,
    operation: str,
) -> Tuple[bool, str]:
    """Push the freshly-rendered body to GitHub after a section mutation.

    Called by every section mutation path (CLI, item_field_transform
    sibling, ``items.section.*`` handlers) after :func:`_rerender_body`
    succeeds. The per-call ``_sync_body`` output is captured into a
    quiet sink so the success-path "Synced body: …" line never leaks
    into the caller's stderr; on transport failure the helper emits a
    structured ``SyncFailed(operation="body")`` event so ``/yoke
    resync --fix`` has the same convergence signal it has for the
    full-field replace path. Returns ``(ok, reason)``: ``ok=True`` on
    dry-run or successful sync; ``ok=False`` with a human-readable
    ``reason`` on transport failure.

    The section mutation is durable regardless — this helper never
    rolls back the DB write. Callers that have a response envelope
    (function-call handlers, ``TransformResult``) surface ``reason`` as
    a ``github_sync_degraded`` warning; CLI callers print it on
    degraded outcome only.
    """
    sink = StringIO()
    try:
        from yoke_core.domain.backlog_rendering import (
            _record_sync_failure,
            _sync_body,
        )
    except ImportError:
        # backlog_rendering is unreachable (deleted-worktree edge case).
        return True, ""
    ok, _mode = _sync_body(
        item_id,
        sink,
        github_timeout_seconds=SECTION_SYNC_GITHUB_TIMEOUT_SECONDS,
        github_max_attempts=SECTION_SYNC_GITHUB_MAX_ATTEMPTS,
    )
    if ok:
        return True, ""
    reason = f"section {operation}: sync_body failed"
    _record_sync_failure(item_id, "body", reason)
    return False, reason


# ---------------------------------------------------------------------------
# Core operations (importable API)
# ---------------------------------------------------------------------------


def upsert_section(
    item_id: int,
    section_name: str,
    content: str,
    *,
    ordering: Optional[int] = None,
    source: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    """Insert or update an ``item_sections`` row.

    When ``ordering`` is ``None`` on update, the existing value is preserved
    via ``COALESCE(excluded.ordering, item_sections.ordering)`` — the existing
    row is table-qualified so the upsert is portable to Postgres, which rejects
    a bare column reference in ``ON CONFLICT DO UPDATE`` as ambiguous. When
    ``source`` is
    omitted, the column default (``'operator'``) applies on insert and the
    existing value is preserved on update (matches the shell's two-branch
    upsert).
    """
    conn = db_helpers.connect(db_path, busy_timeout_ms=BUSY_TIMEOUT_MS)
    try:
        p = _placeholder(conn)
        now_iso = db_helpers.iso8601_now()
        if source:
            conn.execute(
                f"""
                INSERT INTO item_sections (
                    item_id, section_name, content, ordering, source,
                    created_at, updated_at
                )
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})
                ON CONFLICT(item_id, section_name) DO UPDATE SET
                    content = excluded.content,
                    ordering = COALESCE(excluded.ordering, item_sections.ordering),
                    source = excluded.source,
                    updated_at = {p}
                """,
                (item_id, section_name, content, ordering, source,
                 now_iso, now_iso, now_iso),
            )
        else:
            conn.execute(
                f"""
                INSERT INTO item_sections (
                    item_id, section_name, content, ordering,
                    created_at, updated_at
                )
                VALUES ({p}, {p}, {p}, {p}, {p}, {p})
                ON CONFLICT(item_id, section_name) DO UPDATE SET
                    content = excluded.content,
                    ordering = COALESCE(excluded.ordering, item_sections.ordering),
                    updated_at = {p}
                """,
                (item_id, section_name, content, ordering,
                 now_iso, now_iso, now_iso),
            )
        # Section writes (incl. Progress Log appends, which route through
        # this upsert) are real item activity (R1 board-activity semantics).
        from yoke_core.domain.item_activity import touch_item_activity
        touch_item_activity(conn, item_id=item_id)
        conn.commit()
    finally:
        conn.close()


def get_section(
    item_id: int,
    section_name: str,
    *,
    db_path: Optional[str] = None,
) -> Optional[str]:
    """Return the stored content for a section.

    Returns ``None`` when no row matches, ``""`` when the row exists but the
    content column is NULL or empty, otherwise the raw string.
    """
    conn = db_helpers.connect(db_path, busy_timeout_ms=BUSY_TIMEOUT_MS)
    try:
        p = _placeholder(conn)
        row = db_helpers.query_one(
            conn,
            "SELECT COALESCE(content, '') FROM item_sections "
            f"WHERE item_id = {p} AND section_name = {p}",
            (item_id, section_name),
        )
    finally:
        conn.close()
    if row is None:
        return None
    return row[0] or ""


def list_sections(
    item_id: int,
    *,
    db_path: Optional[str] = None,
) -> List[Tuple[str, str, str, str]]:
    """Return ``(name, ordering, created_at, updated_at)`` tuples for an item.

    Ordering column is stringified (empty string when NULL). Row order
    matches the shell: ``COALESCE(ordering, 999999), section_name``.
    """
    conn = db_helpers.connect(db_path, busy_timeout_ms=BUSY_TIMEOUT_MS)
    try:
        p = _placeholder(conn)
        rows = db_helpers.query_rows(
            conn,
            f"""
            SELECT section_name,
                   COALESCE(CAST(ordering AS TEXT), ''),
                   COALESCE(created_at, ''),
                   COALESCE(updated_at, '')
            FROM item_sections
            WHERE item_id = {p}
            ORDER BY COALESCE(ordering, 999999), section_name
            """,
            (item_id,),
        )
    finally:
        conn.close()
    return [(row[0], row[1], row[2], row[3]) for row in rows]


def delete_section(
    item_id: int,
    section_name: str,
    *,
    db_path: Optional[str] = None,
) -> None:
    conn = db_helpers.connect(db_path, busy_timeout_ms=BUSY_TIMEOUT_MS)
    try:
        p = _placeholder(conn)
        conn.execute(
            f"DELETE FROM item_sections WHERE item_id = {p} AND section_name = {p}",
            (item_id, section_name),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI re-exports
# ---------------------------------------------------------------------------
#
# The CLI subcommand handlers and dispatcher live in the sibling
# ``sections_cli`` module. They are imported here at the bottom so consumers
# (and tests using ``sections.cmd_upsert``/``sections.main``) keep a single
# entry-point module. ``sections_cli`` references the package-private
# ``_rerender_body`` and ``_emit_section_event`` helpers above lazily (via
# attribute access on this module at call time), which keeps the module
# graph free of import cycles even when ``sections.py`` is run as
# ``python3 -m yoke_core.domain.sections``.
from yoke_core.domain.sections_cli import (  # noqa: E402
    USAGE,
    cmd_delete,
    cmd_get,
    cmd_list,
    cmd_upsert,
    main,
)


if __name__ == "__main__":
    sys.exit(main())
