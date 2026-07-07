"""CLI wrapper for the ``sections`` domain.

Hosts the ``upsert``/``get``/``list``/``delete`` subcommand handlers and
``main`` dispatcher invoked via ``python3 -m yoke_core.domain.sections``
(re-exported through ``sections.py``) or ``python3 -m yoke_core.cli.db_router
sections``. The core CRUD API and DI hooks live in
``yoke_core.domain.sections``; this module references the package-private
``_rerender_body`` and ``_emit_section_event`` helpers via lazy attribute
access on the sibling so renderer/event-emitter overrides installed via
``set_renderer`` and ``set_event_emitter`` continue to take effect.

Stdout/stderr lines follow the stable sections command contract. See
``sections.py`` for the full output contract.

The sibling ``sections`` module is referenced through a deferred ``import``
inside each handler body. This avoids a cycle on ``python3 -m
yoke_core.domain.sections`` (where the file is registered as ``__main__``
and the package-name re-import races with ``sections_cli``'s own loading).
"""

from __future__ import annotations

import sys
from typing import Iterable, Optional, Sequence, TextIO

from . import db_backend


USAGE = (
    "sections subcommands:\n"
    "\n"
    "  upsert <item-id> <section-name> --content-file <path> "
    "[--ordering N] [--source S]\n"
    "                                        Insert or update a section\n"
    "  get <item-id> <section-name>          Get section content\n"
    "  list <item-id>                        List all sections "
    "(pipe-delimited)\n"
    "  delete <item-id> <section-name>       Delete a section\n"
)

UPSERT_USAGE = (
    "Usage: python3 -m yoke_core.domain.sections upsert "
    "<item-id> <section-name> --content-file <path> "
    "[--ordering N] [--source S]"
)
GET_USAGE = "Usage: python3 -m yoke_core.domain.sections get <item-id> <section-name>"
LIST_USAGE = "Usage: python3 -m yoke_core.domain.sections list <item-id>"
DELETE_USAGE = "Usage: python3 -m yoke_core.domain.sections delete <item-id> <section-name>"


# Deferred imports inside ``cmd_*`` handlers are load-bearing: top-level imports
# cycle through ``sections.py -> sections_cli.py -> sections.py`` under ``-m``.

def _coerce_item_id(raw: str, err: TextIO) -> Optional[int]:
    try:
        return int(raw)
    except (TypeError, ValueError):
        print("Error: invalid item id: {}".format(raw), file=err)
        return None


def cmd_upsert(
    args: Sequence[str],
    *,
    db_path: Optional[str] = None,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
) -> int:
    from yoke_core.domain.sections import (
        _emit_section_event,
        _rerender_body,
        sync_body_after_section_mutation,
        upsert_section,
    )

    if len(args) < 2 or not args[0] or not args[1]:
        print(UPSERT_USAGE, file=err)
        return 2

    item_id_raw = args[0]
    section_name = args[1]
    content_file = ""
    ordering_raw: Optional[str] = None
    source: Optional[str] = None

    i = 2
    while i < len(args):
        token = args[i]
        if token == "--content-file" and i + 1 < len(args):
            content_file = args[i + 1]
            i += 2
        elif token == "--ordering" and i + 1 < len(args):
            ordering_raw = args[i + 1]
            i += 2
        elif token == "--source" and i + 1 < len(args):
            source = args[i + 1]
            i += 2
        else:
            # Mirrors shell: unknown flags are silently skipped.
            i += 1

    if not content_file:
        print(UPSERT_USAGE, file=err)
        return 2

    item_id = _coerce_item_id(item_id_raw, err)
    if item_id is None:
        return 1

    try:
        with open(content_file, "r", encoding="utf-8") as handle:
            content = handle.read()
    except FileNotFoundError:
        print("Error: content file not found: {}".format(content_file), file=err)
        return 1

    ordering: Optional[int] = None
    if ordering_raw:
        try:
            ordering = int(ordering_raw)
        except ValueError:
            print("Error: invalid ordering: {}".format(ordering_raw), file=err)
            return 1

    try:
        upsert_section(
            item_id,
            section_name,
            content,
            ordering=ordering,
            source=source,
            db_path=db_path,
        )
    except db_backend.database_error_types() as exc:
        print("Error: section upsert failed: {}".format(exc), file=err)
        return 1

    print("Upserted section: {} for item {}".format(section_name, item_id), file=out)
    render_ok = _rerender_body(item_id, "upsert", db_path, out, err)
    _emit_section_event("SectionUpserted", item_id, section_name)
    if render_ok:
        # The helper uses its own quiet sink so the per-call gh output
        # never leaks into the caller's stderr; on degraded outcome the
        # caller prints a single structured warning instead.
        sync_ok, sync_reason = sync_body_after_section_mutation(
            item_id, "upsert",
        )
        if not sync_ok:
            print(
                "Warning: github_sync_degraded for YOK-{}: {}".format(
                    item_id, sync_reason,
                ),
                file=err,
            )
    return 0 if render_ok else 1


def cmd_get(
    args: Sequence[str],
    *,
    db_path: Optional[str] = None,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
) -> int:
    from yoke_core.domain.sections import get_section

    if len(args) < 2 or not args[0] or not args[1]:
        print(GET_USAGE, file=err)
        return 2

    item_id = _coerce_item_id(args[0], err)
    if item_id is None:
        return 1

    content = get_section(item_id, args[1], db_path=db_path)
    if content is None:
        return 0
    # Shell: sqlite3 prints the row followed by a newline; cat prints verbatim.
    out.write(content)
    out.write("\n")
    return 0


def cmd_list(
    args: Sequence[str],
    *,
    db_path: Optional[str] = None,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
) -> int:
    from yoke_core.domain.sections import list_sections

    if len(args) < 1 or not args[0]:
        print(LIST_USAGE, file=err)
        return 2

    item_id = _coerce_item_id(args[0], err)
    if item_id is None:
        return 1

    rows = list_sections(item_id, db_path=db_path)
    for name, ordering, created_at, updated_at in rows:
        print("{}|{}|{}|{}".format(name, ordering, created_at, updated_at), file=out)
    return 0


def cmd_delete(
    args: Sequence[str],
    *,
    db_path: Optional[str] = None,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
) -> int:
    from yoke_core.domain.sections import (
        _emit_section_event,
        _rerender_body,
        delete_section,
        sync_body_after_section_mutation,
    )

    if len(args) < 2 or not args[0] or not args[1]:
        print(DELETE_USAGE, file=err)
        return 2

    item_id = _coerce_item_id(args[0], err)
    if item_id is None:
        return 1

    section_name = args[1]
    try:
        delete_section(item_id, section_name, db_path=db_path)
    except db_backend.database_error_types() as exc:
        print("Error: section delete failed: {}".format(exc), file=err)
        return 1

    print("Deleted section: {} for item {}".format(section_name, item_id), file=out)
    render_ok = _rerender_body(item_id, "delete", db_path, out, err)
    _emit_section_event("SectionDeleted", item_id, section_name)
    if render_ok:
        sync_ok, sync_reason = sync_body_after_section_mutation(
            item_id, "delete",
        )
        if not sync_ok:
            print(
                "Warning: github_sync_degraded for YOK-{}: {}".format(
                    item_id, sync_reason,
                ),
                file=err,
            )
    return 0 if render_ok else 1


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])

    # Resolve streams at call time so redirect_stdout/stderr context
    # managers (and other late patches) are honored. Default argument
    # binding would otherwise capture the streams that existed when this
    # module was imported.
    out = sys.stdout
    err = sys.stderr

    if not args:
        print(USAGE, file=err)
        return 2

    sub = args[0]
    rest = args[1:]

    if sub == "upsert":
        return cmd_upsert(rest, out=out, err=err)
    if sub == "get":
        return cmd_get(rest, out=out, err=err)
    if sub == "list":
        return cmd_list(rest, out=out, err=err)
    if sub == "delete":
        return cmd_delete(rest, out=out, err=err)

    print("Error: unknown sections subcommand '{}'".format(sub), file=err)
    print("", file=err)
    print(USAGE, file=err)
    return 2
