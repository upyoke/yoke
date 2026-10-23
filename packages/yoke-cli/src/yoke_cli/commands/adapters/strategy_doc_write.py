"""Strategy document writes with project-aware render destinations.

Destination identity is checked before mutation. An unknown render anchor
may skip local rendering after a successful DB write; it never rolls it back.
Section replacement shares these mutation and rendering helpers.
"""

from __future__ import annotations

from yoke_contracts.project_contract.strategy_doc_fields import fields_rule

import argparse
from yoke_cli.transport.human_values import write_human
import sys
from typing import Any, Dict, List, Optional, Tuple

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
)
from yoke_cli.commands.adapters.strategy_render_client import (
    apply_rendered_docs,
    build_render_payload,
)
from yoke_cli.commands.adapters.strategy_target_project import (
    StrategyTargetRootMismatchError,
    resolve_and_validate_target_root,
    target_root_was_explicit,
)
from yoke_cli.commands.text_file import add_text_file_pair, resolve_text_file
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher, emit_response


__all__ = [
    "resolve_before_mutation",
    "dispatch_and_render",
    "strategy_doc_replace",
    "strategy_doc_archive",
    "strategy_doc_unarchive",
    "STRATEGY_DOC_REPLACE_USAGE",
    "STRATEGY_DOC_ARCHIVE_USAGE",
    "STRATEGY_DOC_UNARCHIVE_USAGE",
]


def resolve_before_mutation(
    target_root_arg,
    *,
    actor,
    target,
    json_mode,
) -> Tuple[Optional[int], Optional[Any], Optional[str]]:
    """Resolve and validate the project destination before any DB write."""
    try:
        target_root = resolve_target_root_for_cli(target_root_arg)
    except RuntimeError as exc:
        return None, None, str(exc)
    explicit_target_root = target_root_was_explicit(target_root_arg)

    identity_response = call_dispatcher(
        function_id="strategy.doc.list",
        target=target,
        payload={},
        actor=actor,
    )
    if not identity_response.success:
        return emit_response(identity_response, json_mode=json_mode), None, None
    identity = identity_response.result or {}
    try:
        target_root = resolve_and_validate_target_root(
            target_root,
            explicit=explicit_target_root,
            project_id=identity.get("project_id"),
            project_slug=identity.get("project_slug"),
        )
    except StrategyTargetRootMismatchError as exc:
        return usage_error(str(exc)), None, None
    return None, target_root, None


def dispatch_and_render(
    *,
    function_id,
    payload,
    actor,
    target,
    json_mode,
    target_root,
    anchor_error,
    skipped_verb: str,
) -> int:
    """Write to the DB, then render or report why local rendering was skipped."""
    mutation_response = call_dispatcher(
        function_id=function_id,
        target=target,
        payload=payload,
        actor=actor,
    )
    if not mutation_response.success:
        return emit_response(mutation_response, json_mode=json_mode)
    if target_root is None:
        print(
            f"warning: strategy doc {skipped_verb}; skipped local render "
            f"— {anchor_error}",
            file=sys.stderr,
        )
        return emit_response(mutation_response, json_mode=json_mode)

    slug = str((payload or {}).get("slug") or "")
    render_response = call_dispatcher(
        function_id="strategy.render.run",
        target=target,
        payload=build_render_payload(
            target_root,
            slugs=[slug] if slug else None,
        ),
        actor=actor,
    )
    if not render_response.success:
        return emit_response(render_response, json_mode=json_mode)

    report, _conflicts = apply_rendered_docs(
        target_root,
        (render_response.result or {}).get("docs", []),
    )

    def _human_writer(response, stdout, stderr) -> None:
        write_human(response.result, stdout)
        if slug in report:
            print(f"{slug}\t{report[slug]}", file=stdout)
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
    "yoke strategy doc replace SLUG --base-updated-at TS "
    "(--content TEXT | --content-file PATH | --stdin) "
    "[--target-root PATH] [--project P] [--force] [--session-id S] [--json]"
)


def strategy_doc_replace(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke strategy doc replace",
        usage=STRATEGY_DOC_REPLACE_USAGE,
        epilog=fields_rule(),
        description=(
            "Replace one strategy doc's full text in the Yoke database, then "
            "render all strategy docs again into the checkout's gitignored "
            ".yoke/strategy/ folder. The new text may be the body alone or a "
            "rendered .yoke/strategy/<slug>.md file; a valid generated header "
            "is dropped before saving. Needs an active STRATEGIZE/FEED process "
            "work claim on the project. If the doc changed after the "
            "--base-updated-at value, the write is refused instead of "
            "overwriting the newer text."
        ),
    )
    parser.add_argument("slug", metavar="SLUG", help="Strategy doc slug, e.g. MISSION.")
    parser.add_argument(
        "--base-updated-at",
        dest="base_updated_at",
        required=True,
        metavar="TS",
        help="The doc's updated_at, as `yoke strategy doc get` showed it.",
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
        help="Allow a much shorter text than the current one (an intended rewrite).",
    )
    parser.add_argument(
        "--target-root",
        dest="target_root",
        default=None,
        metavar="PATH",
        help="Checkout root to render .yoke/strategy/ into (default: as `yoke strategy render`).",
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

    early_exit, target_root, anchor_error = resolve_before_mutation(
        parsed.target_root,
        actor=actor,
        target=target,
        json_mode=parsed.json_mode,
    )
    if early_exit is not None:
        return early_exit

    return dispatch_and_render(
        function_id="strategy.doc.replace",
        payload=payload,
        actor=actor,
        target=target,
        json_mode=parsed.json_mode,
        target_root=target_root,
        anchor_error=anchor_error,
        skipped_verb="replaced in the DB",
    )


STRATEGY_DOC_ARCHIVE_USAGE = (
    "yoke strategy doc archive SLUG [--target-root PATH] "
    "[--project P] [--session-id S] [--json]"
)

STRATEGY_DOC_UNARCHIVE_USAGE = (
    "yoke strategy doc unarchive SLUG [--target-root PATH] "
    "[--project P] [--session-id S] [--json]"
)


def _strategy_doc_set_archived(
    args: List[str],
    *,
    archived: bool,
    function_id: str,
    usage: str,
) -> int:
    """Change archive metadata, then relocate the generated local view."""
    verb = "archive" if archived else "unarchive"
    parser = argparse.ArgumentParser(
        prog=f"yoke strategy doc {verb}",
        usage=usage,
        description=(
            f"{verb.capitalize()} one strategy doc "
            f"({'sets' if archived else 'clears'} archived_at), then render the "
            f"docs again so its file moves {'into' if archived else 'back out of'} "
            ".yoke/strategy/archive/ and the old copy is removed. Nothing is "
            "deleted; the doc stays editable. Refused only while another session "
            "holds the live STRATEGIZE/FEED process work claim for the project."
        ),
    )
    parser.add_argument("slug", metavar="SLUG", help="Strategy doc slug, e.g. INSTALLER-PLAN.")
    parser.add_argument(
        "--target-root",
        dest="target_root",
        default=None,
        metavar="PATH",
        help="Checkout root to render .yoke/strategy/ into (default: as `yoke strategy render`).",
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

    early_exit, target_root, anchor_error = resolve_before_mutation(
        parsed.target_root,
        actor=actor,
        target=target,
        json_mode=parsed.json_mode,
    )
    if early_exit is not None:
        return early_exit

    return dispatch_and_render(
        function_id=function_id,
        payload={"slug": parsed.slug},
        actor=actor,
        target=target,
        json_mode=parsed.json_mode,
        target_root=target_root,
        anchor_error=anchor_error,
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
