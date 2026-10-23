"""``yoke strategy doc section-replace`` adapter.

Split from :mod:`yoke_cli.commands.adapters.strategy_doc_write` for the
authored-file line cap; the resolve-then-write-then-render shape and its two
helpers are that module's, reused here unchanged.

- ``doc section-replace`` -> ``strategy.doc.section_replace``
  (process-claim-gated write), then ``strategy.render.run`` for the slug.
"""

from __future__ import annotations

from yoke_contracts.project_contract.strategy_doc_fields import field_heading

import argparse
import sys
from typing import Any, Dict, List

from yoke_cli.commands import _helpers as _helpers
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_project_arg,
    add_session_arg,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.adapters.strategy import strategy_target
from yoke_cli.commands.adapters.strategy_doc_write import (
    dispatch_and_render,
    resolve_before_mutation,
)
from yoke_cli.commands.text_file import add_text_file_pair, resolve_text_file
from yoke_cli.transport.dispatcher import build_actor


STRATEGY_DOC_SECTION_REPLACE_USAGE = (
    "yoke strategy doc section-replace SLUG --heading TEXT "
    "--base-updated-at TS (--content TEXT | --content-file PATH | --stdin) "
    "[--target-root PATH] [--project P] [--force] [--session-id S] [--json]"
)


def strategy_doc_section_replace(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke strategy doc section-replace",
        usage=STRATEGY_DOC_SECTION_REPLACE_USAGE,
        epilog=(
            f"The document must keep its {field_heading('Summary')} and "
            f"{field_heading('State')} sections present, unique, non-empty "
            "and one line each."
        ),
        description=(
            "Replace the body of one heading in a strategy doc and leave the "
            "rest of the document exactly as it was, then refresh the local "
            ".yoke/strategy/ files. To update one status section, use this "
            "instead of `doc replace`, which rewrites the whole document and "
            "can drop or carry along unrelated edits. "
            "The heading matches at any level, ignoring case. Its section "
            "runs to the next heading at the same level or higher, so "
            "subsections are replaced with it. Pass the body only, without "
            "the heading line. A heading the document does not have is "
            "refused, not added; add a new section with `doc replace`. "
            "You need an active STRATEGIZE or FEED process claim on the "
            "project. --base-updated-at is the updated_at you read with "
            "`yoke strategy doc get`; if the document changed since then, "
            "the write is refused instead of overwriting changes you have "
            "not seen."
        ),
    )
    parser.add_argument(
        "slug", metavar="SLUG", help="Strategy doc slug, e.g. CURRENT-PLAN."
    )
    parser.add_argument(
        "--heading",
        required=True,
        metavar="TEXT",
        help="Heading text of the section to replace, e.g. 'Live status'.",
    )
    parser.add_argument(
        "--base-updated-at",
        dest="base_updated_at",
        required=True,
        metavar="TS",
        help="The document's updated_at when you read it.",
    )
    content_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        content_group,
        "--content",
        "--content-file",
        dest="content",
        help_text="New section body, without its heading line.",
        file_help="Read the new section body from a file.",
    )
    content_group.add_argument(
        "--stdin",
        action="store_true",
        help="Read the new section body from stdin.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow the document to shrink a lot, for an intended rewrite.",
    )
    parser.add_argument(
        "--target-root",
        dest="target_root",
        default=None,
        metavar="PATH",
        help=(
            "Checkout whose .yoke/strategy/ files to refresh (same default "
            "as `yoke strategy render`)."
        ),
    )
    add_project_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRATEGY_DOC_SECTION_REPLACE_USAGE)
    if parsed is None:
        return 2
    if parsed.stdin:
        content = sys.stdin.read()
    else:
        try:
            content = resolve_text_file(
                parsed.content,
                parsed.content_file,
                "--content-file",
            )
        except ValueError as exc:
            return usage_error(str(exc))
    payload: Dict[str, Any] = {
        "slug": parsed.slug,
        "heading": parsed.heading,
        "content": content,
        "base_updated_at": parsed.base_updated_at,
        "force": bool(parsed.force),
    }
    _helpers.ensure_handlers_loaded()
    actor = build_actor(session_id=parsed.session_id)
    target = strategy_target(parsed.project)

    early_exit, target_root, anchor_error = resolve_before_mutation(
        parsed.target_root,
        actor=actor,
        target=target,
        json_mode=parsed.json_mode,
    )
    if early_exit is not None:
        return early_exit

    return dispatch_and_render(
        function_id="strategy.doc.section_replace",
        payload=payload,
        actor=actor,
        target=target,
        json_mode=parsed.json_mode,
        target_root=target_root,
        anchor_error=anchor_error,
        skipped_verb="section replaced in the DB",
    )


__all__ = [
    "STRATEGY_DOC_SECTION_REPLACE_USAGE",
    "strategy_doc_section_replace",
]
