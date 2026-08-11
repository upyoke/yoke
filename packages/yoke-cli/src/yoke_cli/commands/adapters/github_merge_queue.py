"""``yoke github merge-queue apply`` adapter."""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

from yoke_contracts.api.function_call import TargetRef
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)


GITHUB_MERGE_QUEUE_APPLY_USAGE = (
    "yoke github merge-queue apply --project P "
    "[--declaration PATH] [--preview] [--session-id S] [--json]"
)


def github_merge_queue_apply(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github merge-queue apply",
        description=(
            "Idempotently apply .yoke/merge-queue.json (ruleset + "
            "allow_auto_merge) to the project's bound GitHub repository. "
            "Requires Administration: write on the App installation. "
            "Dry-run with --preview."
        ),
    )
    parser.add_argument(
        "--project", required=True,
        help="Project owning the GitHub repo binding.",
    )
    parser.add_argument(
        "--declaration",
        default=None,
        help=(
            "Path to the declared JSON (default: "
            "<checkout>/.yoke/merge-queue.json)."
        ),
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Report planned mutations without writing to GitHub.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, GITHUB_MERGE_QUEUE_APPLY_USAGE,
    )
    if parsed is None:
        return 2

    payload: Dict[str, Any] = {
        "project": parsed.project,
        "preview": parsed.preview,
    }
    if parsed.declaration:
        payload["declaration_path"] = parsed.declaration

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        if response.success:
            print(
                json.dumps(response.result or {}, sort_keys=True),
                file=stdout,
            )
        return None

    return dispatch_and_emit(
        function_id="github.merge_queue.apply",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "GITHUB_MERGE_QUEUE_APPLY_USAGE",
    "github_merge_queue_apply",
]
