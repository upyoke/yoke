"""``yoke strategy doc create`` adapter."""

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
from yoke_cli.commands.adapters.strategy import strategy_target
from yoke_cli.commands.adapters.strategy import (
    resolve_target_root_for_cli,
    write_rendered_files,
)
from yoke_cli.commands.text_file import add_text_file_pair, resolve_text_file
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher, emit_response


STRATEGY_DOC_CREATE_USAGE = (
    "yoke strategy doc create <slug> "
    "(--content TEXT | --content-file PATH | --stdin) "
    "[--target-root PATH] [--project P] [--session-id S] [--json]"
)


def strategy_doc_create(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke strategy doc create",
        description=(
            "Create a new DB-authoritative strategy doc from full content, "
            "then re-render the strategy corpus into .yoke/strategy/. "
            "Use this for brand-new slugs; existing docs should be edited "
            "via `yoke strategy ingest` or replaced with "
            "`yoke strategy doc replace`."
        ),
    )
    parser.add_argument("slug", help="New strategy doc slug, e.g. OPERATIONS-NOTES.")
    content_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        content_group, "--content", "--content-file",
        dest="content",
        help_text="Initial doc content. Use --content-file to read from a path.",
    )
    content_group.add_argument(
        "--stdin", action="store_true",
        help="Read initial doc content from stdin.",
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
    parsed = parse_or_usage_error(parser, args, STRATEGY_DOC_CREATE_USAGE)
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

    _helpers.ensure_handlers_loaded()
    actor = build_actor(session_id=parsed.session_id)
    target = strategy_target(parsed.project)
    create_response = call_dispatcher(
        function_id="strategy.doc.create",
        target=target,
        payload={"slug": parsed.slug, "content": content},
        actor=actor,
    )
    if not create_response.success:
        return emit_response(create_response, json_mode=parsed.json_mode)

    try:
        target_root = resolve_target_root_for_cli(parsed.target_root)
    except RuntimeError as exc:
        print(
            "warning: strategy doc created in the DB; skipped local "
            f"render -- {exc}",
            file=sys.stderr,
        )
        return emit_response(create_response, json_mode=parsed.json_mode)

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
        create_response,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = ["STRATEGY_DOC_CREATE_USAGE", "strategy_doc_create"]
