"""Safe additive transforms on structured item fields.

Replaces ad hoc shell choreography (read field to /tmp, transform, pipe back
to ``items update --stdin``) with a Python-owned helper. The helper reads the
current field through canonical DB routing, applies an additive operation
(idempotent ``## heading`` append, rendered-section upsert, or
``item_sections`` append),
writes through :func:`yoke_core.domain.backlog_structured_write_op.execute_structured_write`
or the ``sections`` owner, re-reads to verify, and returns structured
evidence.

Empty new content is refused before any write. Shrinkage/freeze/empty
guards on ``execute_structured_write`` are preserved -- the helper never
provides a silent bypass. Section-scoped operations live in
:mod:`yoke_core.domain.item_field_transform_sections`, keeping this
dispatcher under the 350-line file budget while exposing one CLI surface
to operators.

CLI::

    python3 -m yoke_core.domain.item_field_transform append-addendum \\
        --item YOK-N --field spec --heading "Refinement Addendum" \\
        [--source refine] (--stdin | --body-file PATH)

    python3 -m yoke_core.domain.item_field_transform section-upsert \\
        --item YOK-N --section "Progress Log" [--ordering 200] \\
        [--source refine] (--stdin | --body-file PATH)

    python3 -m yoke_core.domain.item_field_transform section-append \\
        --item YOK-N --section "Progress Log" --headline "<headline>" \\
        [--ordering 200] [--source refine] (--stdin | --body-file PATH)
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from typing import Optional, TextIO

from yoke_core.domain.backlog_queries import (
    VALID_STRUCTURED_FIELDS,
    _query_item_field,
    _resolve_write_db_path,
)
from yoke_core.domain.backlog_structured_write_op import execute_structured_write
from yoke_core.domain.db_helpers import connect


_APPEND_ADDENDUM = "append-addendum"


def parse_item_id(raw: str) -> int:
    """Delegate to :mod:`yoke_core.domain.yok_n_parser`.

    Kept as a re-export so call sites that import ``parse_item_id`` from
    this module continue to work without churn.
    """
    from yoke_core.domain.yok_n_parser import parse_item_id as _shared

    return _shared(raw, allow_bare_internal=True)


@dataclass(frozen=True)
class TransformResult:
    """Structured evidence returned by every transform operation."""

    success: bool
    operation: str
    item_id: Optional[int] = None
    field: str = ""
    heading: str = ""
    section: str = ""
    changed: bool = False
    old_line_count: int = 0
    new_line_count: int = 0
    verification: str = ""
    warning: str = ""
    body_sync_mode: str = ""
    body_sync_elapsed_ms: int = 0
    error: str = ""

    def to_json(self) -> str:
        # Drop empty optional fields so consumers see only what applies.
        payload = {
            key: value
            for key, value in asdict(self).items()
            if value not in ("", None) or key in ("success", "changed")
        }
        return json.dumps(payload, sort_keys=True)


def _line_count(text: str) -> int:
    if not text:
        return 0
    trailing = 0 if text.endswith("\n") else 1
    return text.count("\n") + trailing


def _has_top_level_heading(content: str, heading: str) -> bool:
    if not content or not heading:
        return False
    target = f"## {heading.strip()}"
    return any(line.rstrip() == target for line in content.splitlines())


def _build_addendum(existing: str, heading: str, body: str) -> str:
    """Concatenate ``existing`` + ``## heading`` block, blank-line separated."""
    block = f"## {heading.strip()}\n{body.rstrip()}\n"
    if not existing:
        return block
    if existing.endswith("\n\n"):
        return existing + block
    if existing.endswith("\n"):
        return existing + "\n" + block
    return existing + "\n\n" + block


def _fail(operation: str, error: str, **fields) -> TransformResult:
    return TransformResult(
        success=False, operation=operation, error=error, **fields,
    )


class _NullSink:
    """Discard inner-write log lines while still satisfying ``TextIO``."""

    def write(self, _data: str) -> int:  # pragma: no cover - trivial
        return 0

    def flush(self) -> None:  # pragma: no cover - trivial
        return None


def append_addendum(
    *,
    item_id: int,
    field: str,
    heading: str,
    content: str,
    source: str = "",
    rebuild_board: bool = True,
    out: Optional[TextIO] = None,
) -> TransformResult:
    """Append a ``## heading``-led addendum to a structured field.

    Idempotency: when an exact ``## heading`` line already exists at the top
    level, the operation is a no-op (``changed=False``,
    ``verification="heading-already-present"``).
    """
    op = _APPEND_ADDENDUM
    common = {"item_id": item_id, "field": field, "heading": heading}
    if field not in VALID_STRUCTURED_FIELDS:
        return _fail(op, f"invalid structured field: {field}", **common)
    if not heading or not heading.strip():
        return _fail(op, "heading is required", item_id=item_id, field=field)
    if content is None or not content.strip():
        return _fail(op, "refusing addendum with empty content", **common)

    existing = _read_field(item_id, field) or ""
    old_lines = _line_count(existing)

    if _has_top_level_heading(existing, heading):
        return TransformResult(
            success=True, operation=op, item_id=item_id, field=field,
            heading=heading, changed=False, old_line_count=old_lines,
            new_line_count=old_lines, verification="heading-already-present",
        )

    updated = _build_addendum(existing, heading, content)
    write_result = execute_structured_write(
        item_id=item_id, field=field, content=updated, source=source,
        rebuild_board=rebuild_board,
        out=out if out is not None else _NullSink(),
    )
    if not write_result.get("success"):
        return _fail(
            op, str(write_result.get("error") or "structured write failed"),
            **common, old_line_count=old_lines,
        )

    persisted = _read_field(item_id, field) or ""
    new_lines = _line_count(persisted)
    if not _has_top_level_heading(persisted, heading):
        return _fail(
            op, "post-write verification failed: heading not present",
            **common, old_line_count=old_lines,
            new_line_count=new_lines, verification="missing",
        )
    return TransformResult(
        success=True, operation=op, item_id=item_id, field=field,
        heading=heading, changed=True, old_line_count=old_lines,
        new_line_count=new_lines, verification="ok",
        warning=str(write_result.get("sync_warning") or ""),
    )


def _read_field(item_id: int, field: str) -> Optional[str]:
    db_path = _resolve_write_db_path()
    conn = connect(db_path)
    try:
        return _query_item_field(conn, item_id, field)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Section operations live in the sibling module to keep this dispatcher
# under the 350-line file budget. They're re-exported here so callers can
# continue to use ``item_field_transform.section_upsert`` /
# ``item_field_transform.section_append`` without learning a new import
# path. The sibling imports ``TransformResult``, ``_NullSink``, and
# ``_line_count`` from this module; placing the import below those
# definitions avoids the partial-load circular trap.
# ---------------------------------------------------------------------------

from yoke_core.domain.item_field_transform_sections import (  # noqa: E402
    SECTION_APPEND as _SECTION_APPEND,
    SECTION_UPSERT as _SECTION_UPSERT,
    section_append,
    section_upsert,
)


# ---------------------------------------------------------------------------
# CLI dispatch — implementation lives in the sibling ``item_field_transform_cli``
# module so the top-level CLI can route through the function dispatcher
# while this module stays under the 350-line file budget.
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    """Delegate to the sibling CLI dispatcher.

    The sibling parses argv, builds a ``FunctionCallRequest``, calls
    :func:`yoke_core.domain.yoke_function_dispatch.dispatch`, and
    emits human stdout (default) or the typed envelope (``--json``).

    Synonym normalization runs first: ``section-upsert`` accepts
    ``--field <name>`` or ``--heading <name>`` as synonyms for
    ``--section`` so operators do not need to learn two vocabularies for
    naming the section being upserted. Synonyms are translated to the
    canonical ``--section`` form before the sibling parser sees argv.
    """
    from yoke_core.domain.item_field_transform_cli import main as _cli_main

    return _cli_main(_normalize_section_synonyms(argv))


def _normalize_section_synonyms(argv: Optional[list[str]]) -> Optional[list[str]]:
    """Map ``--field`` / ``--heading`` to ``--section`` for section-upsert.

    Only applies when the first token is ``section-upsert`` so the
    addendum subcommand's existing ``--field`` and ``--heading`` flags
    are not clobbered. Returns the rewritten argv (a new list) or the
    original input when no rewrite applies.
    """
    if argv is None or not argv:
        return argv
    if argv[0] != "section-upsert":
        return argv
    rewritten: list[str] = [argv[0]]
    i = 1
    seen_canonical = False
    while i < len(argv):
        token = argv[i]
        if token in ("--field", "--heading"):
            if i + 1 < len(argv) and not seen_canonical:
                rewritten.extend(["--section", argv[i + 1]])
                i += 2
                continue
            # Malformed (trailing flag) or duplicate synonym: pass
            # through so argparse emits its own diagnostic.
            rewritten.append(token)
            i += 1
            continue
        if token == "--section":
            seen_canonical = True
        rewritten.append(token)
        i += 1
    return rewritten


__all__ = [
    "TransformResult",
    "append_addendum",
    "main",
    "parse_item_id",
    "section_append",
    "section_upsert",
]


if __name__ == "__main__":  # pragma: no cover - CLI shim
    sys.exit(main())
