"""Render item body from structured fields.

Pure render helper — assembles a rendered body string from structured item
fields, ``item_sections``, and Shepherd log output.  Zero DB writes, zero
file writes, zero backlog-markdown regeneration, zero GitHub sync, zero
cache-era telemetry side effects.

Callers invoke via ``python3 -m yoke_core.domain.render_body <item-id>``.
"""

from __future__ import annotations

import sys
from typing import Any, Iterable, Optional, TextIO

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, query_one, query_rows, query_scalar
from yoke_core.domain.path_claims_render import render_path_claims_section
from yoke_core.domain.render_body_blocked import render_blocked_section
from yoke_core.domain.render_body_epic_notes import render_epic_progress_notes_section
from yoke_core.domain.render_body_db_claim import (
    DB_CLAIM_ATTESTATION_SUBHEADING,
    DB_CLAIM_HEADING,
    render_db_claim_section,
)
from yoke_core.domain.render_body_section import (
    RENDERER_OWNED_BODY_HEADINGS,
    extract_section,
    render_section_block as _render_section,
    section_has_content as _section_has_content,
    strip_duplicate_heading as _strip_duplicate_heading,
    strip_renderer_owned_sections as _strip_renderer_owned_sections,
    strip_spec_h1 as _strip_spec_h1,
)
from yoke_core.domain.schema_common import (
    _get_columns as _schema_get_columns,
    _table_exists as _schema_table_exists,
)
from yoke_core.domain.shepherd import cmd_shepherd_log


STRUCTURED_FIELDS = (
    "spec",
    "design_spec",
    "technical_plan",
    "worktree_plan",
    "shepherd_caveats",
    "test_results",
    "deploy_log",
)

__all__ = [
    "STRUCTURED_FIELDS",
    "DB_CLAIM_HEADING",
    "DB_CLAIM_ATTESTATION_SUBHEADING",
    "build_body",
    "render_item",
    "render_section",
    "main",
]


def _normalize_item_id(raw: str) -> int:
    value = raw.strip()
    if value.upper().startswith("YOK-"):
        value = value[4:]
    return int(value)


def _usage_error(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _fetch_item(conn: Any, item_id: int):
    # Dynamically select only columns that exist (resilient to partial schemas in tests)
    available = set(_schema_get_columns(conn, "items"))
    wanted = ["id", "title", "spec", "design_spec", "technical_plan",
              "worktree_plan", "shepherd_caveats", "test_results", "deploy_log",
              "db_mutation_profile", "db_compatibility_attestation",
              "architecture_impact"]
    cols = [c for c in wanted if c in available]
    if "id" not in cols:
        return None
    p = _p(conn)
    return query_one(
        conn,
        f"SELECT {', '.join(cols)} FROM items WHERE id = {p}",
        (item_id,),
    )


def _fetch_sections(
    conn: Any,
    item_id: int,
    *,
    min_ordering: int,
    max_ordering: int,
) -> list[Any]:
    p = _p(conn)
    return query_rows(
        conn,
        f"""
        SELECT section_name, content
        FROM item_sections
        WHERE item_id = {p}
          AND ordering >= {p}
          AND ordering < {p}
        ORDER BY ordering, section_name
        """,
        (item_id, min_ordering, max_ordering),
    )


def _has_any_content(conn: Any, item_id: int, row, row_keys: set) -> bool:
    """Return True if the item has any structured field, section, shepherd log, or progress note."""
    if any(
        field in row_keys and _section_has_content(row[field])
        for field in STRUCTURED_FIELDS
    ):
        return True
    p = _p(conn)
    if _schema_table_exists(conn, "item_sections") and query_scalar(
        conn, f"SELECT COUNT(*) FROM item_sections WHERE item_id = {p}", (item_id,)
    ):
        return True
    if _schema_table_exists(conn, "shepherd_verdicts") and query_scalar(
        conn, f"SELECT COUNT(*) FROM shepherd_verdicts WHERE item = {p}",
        (f"YOK-{item_id}",),
    ):
        return True
    if _schema_table_exists(conn, "epic_progress_notes") and query_scalar(
        conn, f"SELECT COUNT(*) FROM epic_progress_notes WHERE epic_id = {p}",
        (str(item_id),),
    ):
        return True
    return False


def _append_field_section(chunks: list[str], heading: str, content: Optional[str]) -> None:
    if _section_has_content(content):
        chunks.append(
            _render_section(heading, _strip_duplicate_heading(str(content), heading))
        )


def _append_item_sections(
    chunks: list[str], conn: Any, item_id: int,
    *, min_ordering: int, max_ordering: int,
) -> None:
    if not _schema_table_exists(conn, "item_sections"):
        return
    for sec_row in _fetch_sections(
        conn, item_id, min_ordering=min_ordering, max_ordering=max_ordering,
    ):
        content = sec_row["content"]
        if _section_has_content(content):
            chunks.append(
                _render_section(f"## {sec_row['section_name']}", str(content))
            )


def build_body(conn: Any, item_id: int) -> Optional[str]:
    """Assemble rendered body from structured fields. Pure — no side effects."""
    row = _fetch_item(conn, item_id)
    if row is None:
        return None
    row_keys = set(row.keys()) if hasattr(row, 'keys') else set()
    if not _has_any_content(conn, item_id, row, row_keys):
        return ""

    chunks: list[str] = []

    def _get(field: str) -> Optional[str]:
        return row[field] if field in row_keys else None

    title = _get("title") or ""
    blocked_section = render_blocked_section(conn, item_id)
    if blocked_section:
        chunks.append(blocked_section)

    spec = _get("spec")
    if _section_has_content(spec):
        cleaned = _strip_renderer_owned_sections(
            _strip_spec_h1(str(spec)), RENDERER_OWNED_BODY_HEADINGS,
        )
        if _section_has_content(cleaned):
            chunks.append(_render_section(f"# Spec: {title}", cleaned))

    _append_field_section(chunks, "## Design Spec", _get("design_spec"))

    db_claim_section = render_db_claim_section(
        _get("db_mutation_profile"),
        _get("db_compatibility_attestation"),
    )
    if db_claim_section:
        chunks.append(db_claim_section)

    from yoke_core.domain.render_body_architecture import render_architecture_impact_section
    arch_section = render_architecture_impact_section(_get("architecture_impact"))
    if arch_section:
        chunks.append(arch_section)

    path_claims_section = render_path_claims_section(conn, item_id)
    if path_claims_section:
        chunks.append(path_claims_section)

    _append_field_section(chunks, "## Technical Plan", _get("technical_plan"))
    _append_field_section(chunks, "## Worktree Plan", _get("worktree_plan"))
    _append_item_sections(chunks, conn, item_id, min_ordering=0, max_ordering=500)
    _append_field_section(chunks, "## Shepherd Caveats", _get("shepherd_caveats"))

    if _schema_table_exists(conn, "shepherd_verdicts"):
        try:
            shepherd_log = cmd_shepherd_log(conn, f"YOK-{item_id}")
            if len(shepherd_log.splitlines()) > 3:
                chunks.append(shepherd_log.rstrip("\n"))
        except Exception:
            # Postgres aborts the whole transaction on a failed statement, so
            # roll back to keep later reads alive (SQLite no-op, read-only path).
            conn.rollback()

    progress_notes_section = render_epic_progress_notes_section(conn, item_id)
    if progress_notes_section:
        chunks.append(progress_notes_section)

    _append_field_section(chunks, "## Test Results", _get("test_results"))
    _append_field_section(chunks, "## Deploy Log", _get("deploy_log"))
    _append_item_sections(chunks, conn, item_id, min_ordering=500, max_ordering=999999)

    body = "\n\n".join(chunk.rstrip("\n") for chunk in chunks if chunk != "")
    if body and not body.endswith("\n"):
        body += "\n"
    return body


def render_item(
    item_id: int,
    *,
    db_path: Optional[str] = None,
    output_file: Optional[str] = None,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
) -> int:
    """Render an item's body and print or write to file. Pure — no DB writes."""
    conn = connect(db_path)
    try:
        body = build_body(conn, item_id)
        if body is None:
            print(f"Error: item YOK-{item_id} not found", file=err)
            return 1

        if output_file is not None:
            from pathlib import Path
            Path(output_file).write_text(body, encoding="utf-8")
            return 0

        out.write(body)
        return 0
    finally:
        conn.close()


def render_section(
    item_id: int,
    section: str,
    *,
    db_path: Optional[str] = None,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
) -> int:
    """Render a single ``## <section>`` block from an item's body.

    Returns 0 on success or when the heading is absent (stdout empty,
    advisory on stderr — section absence is normal data, not error,
    so parallel tool-call siblings stay alive). Returns 1 only when
    the item id does not exist.
    """
    conn = connect(db_path)
    try:
        body = build_body(conn, item_id)
        if body is None:
            print(f"Error: item YOK-{item_id} not found", file=err)
            return 1
        content = extract_section(body, section)
        if content is None:
            print(
                f"Advisory: section '{section}' not found on YOK-{item_id}",
                file=err,
            )
            return 0
        if content:
            out.write(content)
            if not content.endswith("\n"):
                out.write("\n")
        return 0
    finally:
        conn.close()


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    usage = (
        "Usage: python3 -m yoke_core.domain.render_body <item-id> "
        "[--output-file <path>] [--section \"## Heading\"]"
    )
    if not args:
        return _usage_error(usage)

    try:
        item_id = _normalize_item_id(args[0])
    except ValueError:
        return _usage_error(usage)

    output_file: Optional[str] = None
    section: Optional[str] = None
    rest = args[1:]
    i = 0
    while i < len(rest):
        token = rest[i]
        if token == "--output-file":
            if i + 1 >= len(rest):
                return _usage_error("Error: --output-file requires a path argument")
            output_file = rest[i + 1]
            i += 2
            continue
        if token == "--section":
            if i + 1 >= len(rest):
                return _usage_error("Error: --section requires a heading argument")
            section = rest[i + 1]
            i += 2
            continue
        return _usage_error(f"Error: unknown argument '{token}'")

    try:
        if section is not None:
            return render_section(item_id, section)
        return render_item(item_id, output_file=output_file)
    except FileNotFoundError:
        print("Error: cannot resolve Yoke DB authority", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
