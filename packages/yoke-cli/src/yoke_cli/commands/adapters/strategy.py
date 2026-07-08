"""``yoke strategy doc *`` adapters (list / get / replace).

Per-project DB-authoritative strategy documents (each project's
``.yoke/strategy/`` files are a gitignored local rendered view, a
regenerated cache):

- ``doc list`` -> ``strategy.doc.list`` (slug/updated_at/bytes table).
- ``doc get`` -> ``strategy.doc.get`` (content to stdout in human mode).
- ``doc replace`` -> ``strategy.doc.replace`` (process-claim-gated write),
  then ``strategy.render.run`` for the full local rendered view.

Project context resolves client-side (``--project`` flag >
``$YOKE_PROJECT`` > the machine-config checkout→project map) and
rides on ``target.project_id``; the render/ingest/seed-defaults
siblings live in :mod:`yoke_cli.commands.adapters.strategy_render`.
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
    client_project_context,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.text_file import add_text_file_pair, resolve_text_file
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher, emit_response
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.project_contract.strategy_docs_io import write_rendered_files
from yoke_contracts.project_contract.workspace_roots import resolve_target_root_for_cli


__all__ = [
    "strategy_doc_list",
    "strategy_doc_get",
    "strategy_doc_replace",
    "strategy_target",
    "resolve_target_root_for_cli",
    "write_rendered_files",
    "STRATEGY_DOC_LIST_USAGE",
    "STRATEGY_DOC_GET_USAGE",
    "STRATEGY_DOC_REPLACE_USAGE",
]


def strategy_target(project: Any) -> TargetRef:
    """Global-kind target carrying the client-resolved project context."""
    return TargetRef(kind="global", project_id=client_project_context(project))


STRATEGY_DOC_LIST_USAGE = (
    "yoke strategy doc list [--project P] [--session-id S] [--json]"
)


def strategy_doc_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke strategy doc list",
        description=(
            "List the project's DB-authoritative strategy docs (slug, "
            "updated_at, bytes). The repo .yoke/strategy/ directory is "
            "a rendered view."
        ),
    )
    add_project_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRATEGY_DOC_LIST_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        print(
            f"project {result.get('project_slug')} ({result.get('project_id')})",
            file=stdout,
        )
        for doc in result.get("docs", []):
            print(
                f"{doc.get('slug')}\t{doc.get('updated_by') or '-'}\t"
                f"{doc.get('updated_at')}\t{doc.get('bytes')} bytes",
                file=stdout,
            )

    return dispatch_and_emit(
        function_id="strategy.doc.list",
        target=strategy_target(parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


STRATEGY_DOC_GET_USAGE = (
    "yoke strategy doc get <slug> [--project P] [--session-id S] [--json]"
)


def strategy_doc_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke strategy doc get",
        description=(
            "Print one strategy doc's DB-authoritative content to stdout "
            "(e.g. slug MISSION or MASTER-PLAN) for the project."
        ),
    )
    parser.add_argument("slug", help="Strategy doc slug, e.g. MISSION.")
    add_project_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRATEGY_DOC_GET_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        stdout.write(str((response.result or {}).get("content", "")))

    return dispatch_and_emit(
        function_id="strategy.doc.get",
        target=strategy_target(parsed.project),
        payload={"slug": parsed.slug},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
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
            "corpus into the checkout's tracked .yoke/strategy/ view. "
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
        "--base-updated-at", dest="base_updated_at", required=True,
        help="The updated_at the new content was authored against.",
    )
    content_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        content_group, "--content", "--content-file",
        dest="content",
        help_text="New doc content. Use --content-file to read from a path.",
    )
    content_group.add_argument(
        "--stdin", action="store_true",
        help="Read new doc content from stdin.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Bypass the shrink guard for an intentional rewrite.",
    )
    parser.add_argument(
        "--target-root", dest="target_root", default=None,
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
                parsed.content, parsed.content_file, "--content-file",
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

    # The DB write is the authority and it landed. The local render is a
    # convenience refresh, so its anchor is resolved only now: a failed
    # replace never needs --target-root, and an unresolvable anchor (a
    # linked worktree without --target-root) warns and skips the render
    # rather than orphaning the successful write.
    try:
        target_root = resolve_target_root_for_cli(parsed.target_root)
    except RuntimeError as exc:
        print(
            "warning: strategy doc replaced in the DB; skipped local "
            f"render — {exc}",
            file=sys.stderr,
        )
        return emit_response(replace_response, json_mode=parsed.json_mode)

    render_response = call_dispatcher(
        function_id="strategy.render.run",
        target=target,
        payload={},
        actor=actor,
    )
    if not render_response.success:
        return emit_response(render_response, json_mode=parsed.json_mode)

    report = write_rendered_files(
        target_root, (render_response.result or {}).get("docs", []),
    )

    def _human_writer(response, stdout, stderr) -> None:
        print(json.dumps(response.result, sort_keys=True), file=stdout)
        for slug, status in report.items():
            print(f"{slug}\t{status}", file=stdout)
        for warning in response.warnings:
            print(
                f"warning: {warning.code} ({warning.step}): "
                f"{warning.detail}",
                file=stderr,
            )

    return emit_response(
        replace_response,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )
