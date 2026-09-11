"""``yoke strategy doc replace|archive|unarchive`` adapters.

Split from :mod:`yoke_cli.commands.adapters.strategy` (which owns the
read-only ``doc list``/``doc get`` pair) to respect the authored-file
line cap: these three commands share the same write-then-render shape.

- ``doc replace`` -> ``strategy.doc.replace`` (process-claim-gated write),
  then ``strategy.render.run`` for the full local rendered view.
- ``doc archive`` / ``doc unarchive`` -> ``strategy.doc.archive`` /
  ``strategy.doc.unarchive`` (flip the archived state), then
  ``strategy.render.run`` so the file relocates to/from
  ``.yoke/strategy/archive/`` and the stale sibling is pruned.

The DB write is the authority and lands first; the local render is a
convenience refresh, so its checkout anchor is resolved and validated
only after a successful write — never before, and never in a way that
implies the write itself failed or rolled back.
:mod:`yoke_cli.commands.adapters.strategy_target_project` supplies that
project-aware anchor validation, so a write for one project can never
render into a different project's checkout (field note 49342).
"""

from __future__ import annotations

import argparse
import json
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
from yoke_cli.commands.adapters.strategy import (
    resolve_target_root_for_cli,
    strategy_target,
    write_rendered_files,
)
from yoke_cli.commands.adapters.strategy_target_project import (
    StrategyTargetRootMismatchError,
    resolve_and_validate_target_root,
    target_root_was_explicit,
)
from yoke_cli.commands.text_file import add_text_file_pair, resolve_text_file
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher, emit_response


__all__ = [
    "strategy_doc_replace",
    "strategy_doc_archive",
    "strategy_doc_unarchive",
    "STRATEGY_DOC_REPLACE_USAGE",
    "STRATEGY_DOC_ARCHIVE_USAGE",
    "STRATEGY_DOC_UNARCHIVE_USAGE",
]


def _refresh_render(
    mutation_response,
    *,
    target_root_arg,
    actor,
    target,
    json_mode,
    skipped_verb: str,
):
    """Re-render the corpus into the validated anchor after a landed write.

    Shared by ``doc replace`` and ``doc archive``/``doc unarchive``: an
    unresolvable anchor or a project mismatch both warn and skip the
    local render rather than failing the command — the DB write already
    landed. Returns the emit-ready return code.
    """
    try:
        target_root = resolve_target_root_for_cli(target_root_arg)
    except RuntimeError as exc:
        print(
            f"warning: strategy doc {skipped_verb}; skipped local render — {exc}",
            file=sys.stderr,
        )
        return emit_response(mutation_response, json_mode=json_mode)
    explicit_target_root = target_root_was_explicit(target_root_arg)

    mutation_result = mutation_response.result or {}
    try:
        target_root = resolve_and_validate_target_root(
            target_root,
            explicit=explicit_target_root,
            project_id=mutation_result.get("project_id"),
            project_slug=mutation_result.get("project_slug"),
        )
    except StrategyTargetRootMismatchError as exc:
        print(
            f"warning: strategy doc {skipped_verb}; skipped local render — {exc}",
            file=sys.stderr,
        )
        return emit_response(mutation_response, json_mode=json_mode)

    render_response = call_dispatcher(
        function_id="strategy.render.run",
        target=target,
        payload={},
        actor=actor,
    )
    if not render_response.success:
        return emit_response(render_response, json_mode=json_mode)

    report = write_rendered_files(
        target_root,
        (render_response.result or {}).get("docs", []),
    )

    def _human_writer(response, stdout, stderr) -> None:
        print(json.dumps(response.result, sort_keys=True), file=stdout)
        for slug, status in report.items():
            print(f"{slug}\t{status}", file=stdout)
        for warning in response.warnings:
            print(
                f"warning: {warning.code} ({warning.step}): {warning.detail}",
                file=stderr,
            )

    return emit_response(
        mutation_response,
        json_mode=json_mode,
        human_writer=_human_writer,
    )


STRATEGY_DOC_REPLACE_USAGE = (
    "yoke strategy doc replace <slug> --base-updated-at TS "
    "(--content TEXT | --content-file PATH | --stdin) "
    "[--target-root PATH] [--project P] [--force] [--session-id S] [--json]"
)


def strategy_doc_replace(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke strategy doc replace",
        description=(
            "Replace one strategy doc's full content in the Yoke DB "
            "(the authority), then re-render the latest full strategy "
            "corpus into the checkout's gitignored .yoke/strategy/ view. "
            "Replacement content may be header-free body or a rendered "
            ".yoke/strategy/<slug>.md file; a valid generated header is "
            "ignored before storage. "
            "Requires an active STRATEGIZE/FEED "
            "process work-claim on the target project, and every write "
            "is compare-and-swap: --base-updated-at carries the "
            "updated_at you read via `yoke strategy doc get` so a "
            "moved row refuses instead of losing the newer content."
        ),
    )
    parser.add_argument("slug", help="Strategy doc slug, e.g. MISSION.")
    parser.add_argument(
        "--base-updated-at",
        dest="base_updated_at",
        required=True,
        help="The updated_at the new content was authored against.",
    )
    content_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        content_group,
        "--content",
        "--content-file",
        dest="content",
        help_text="New doc content. Use --content-file to read from a path.",
    )
    content_group.add_argument(
        "--stdin",
        action="store_true",
        help="Read new doc content from stdin.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass the shrink guard for an intentional rewrite.",
    )
    parser.add_argument(
        "--target-root",
        dest="target_root",
        default=None,
        help=(
            "Checkout root receiving the refreshed .yoke/strategy/ files "
            "(defaults like `yoke strategy render`)."
        ),
    )
    add_project_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRATEGY_DOC_REPLACE_USAGE)
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
        "content": content,
        "base_updated_at": parsed.base_updated_at,
        "force": bool(parsed.force),
    }
    _helpers.ensure_handlers_loaded()
    actor = build_actor(session_id=parsed.session_id)
    target = strategy_target(parsed.project)
    replace_response = call_dispatcher(
        function_id="strategy.doc.replace",
        target=target,
        payload=payload,
        actor=actor,
    )
    if not replace_response.success:
        return emit_response(replace_response, json_mode=parsed.json_mode)

    return _refresh_render(
        replace_response,
        target_root_arg=parsed.target_root,
        actor=actor,
        target=target,
        json_mode=parsed.json_mode,
        skipped_verb="replaced in the DB",
    )


STRATEGY_DOC_ARCHIVE_USAGE = (
    "yoke strategy doc archive <slug> [--target-root PATH] "
    "[--project P] [--session-id S] [--json]"
)

STRATEGY_DOC_UNARCHIVE_USAGE = (
    "yoke strategy doc unarchive <slug> [--target-root PATH] "
    "[--project P] [--session-id S] [--json]"
)


def _strategy_doc_set_archived(
    args: List[str],
    *,
    archived: bool,
    function_id: str,
    usage: str,
) -> int:
    """Flip a doc's archived state, then re-render so the file relocates.

    Shared body for ``doc archive`` / ``doc unarchive``: dispatch the DB
    flip (the authority), then re-render the full corpus so the doc moves
    into/out of ``.yoke/strategy/archive/`` and the stale sibling is
    pruned. Mirrors ``doc replace``'s render-refresh, including the
    warn-and-skip when no checkout anchor resolves or the anchor belongs
    to a different project.
    """
    verb = "archive" if archived else "unarchive"
    parser = argparse.ArgumentParser(
        prog=f"yoke strategy doc {verb}",
        description=(
            f"{verb.capitalize()} one strategy doc on its DB row "
            f"({'stamps' if archived else 'clears'} archived_at), then "
            "re-render the corpus so the rendered file "
            f"{'moves into' if archived else 'moves back out of'} "
            ".yoke/strategy/archive/ and the stale sibling is pruned. The "
            "doc stays a full, editable row either way — nothing is "
            "deleted. Refused only while another session holds the live "
            "STRATEGIZE/FEED process work-claim for the project."
        ),
    )
    parser.add_argument("slug", help="Strategy doc slug, e.g. INSTALLER-PLAN.")
    parser.add_argument(
        "--target-root",
        dest="target_root",
        default=None,
        help=(
            "Checkout root receiving the refreshed .yoke/strategy/ files "
            "(defaults like `yoke strategy render`)."
        ),
    )
    add_project_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2

    _helpers.ensure_handlers_loaded()
    actor = build_actor(session_id=parsed.session_id)
    target = strategy_target(parsed.project)
    flip_response = call_dispatcher(
        function_id=function_id,
        target=target,
        payload={"slug": parsed.slug},
        actor=actor,
    )
    if not flip_response.success:
        return emit_response(flip_response, json_mode=parsed.json_mode)

    return _refresh_render(
        flip_response,
        target_root_arg=parsed.target_root,
        actor=actor,
        target=target,
        json_mode=parsed.json_mode,
        skipped_verb=f"{verb}d in the DB",
    )


def strategy_doc_archive(args: List[str]) -> int:
    return _strategy_doc_set_archived(
        args,
        archived=True,
        function_id="strategy.doc.archive",
        usage=STRATEGY_DOC_ARCHIVE_USAGE,
    )


def strategy_doc_unarchive(args: List[str]) -> int:
    return _strategy_doc_set_archived(
        args,
        archived=False,
        function_id="strategy.doc.unarchive",
        usage=STRATEGY_DOC_UNARCHIVE_USAGE,
    )
