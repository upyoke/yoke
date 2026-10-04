"""Reversible project retirement adapters."""

from __future__ import annotations

import argparse

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef

USAGE_BY_FUNCTION_ID = {
    "projects.retire": "yoke projects retire --project P --reason TEXT [--json]",
    "projects.unretire": "yoke projects unretire --project P [--json]",
}


def _run(args, *, retired):
    verb = "retire" if retired else "unretire"
    usage = USAGE_BY_FUNCTION_ID[f"projects.{verb}"]
    parser = argparse.ArgumentParser(
        prog=f"yoke projects {verb}",
        description="Hide or restore a project without deleting history. Retirement "
        "refuses open items, created/executing runs, and held claims; finish those "
        "obligations before retrying. Lists omit retired projects unless "
        "--include-retired is selected; direct project reads retain history.",
    )
    parser.add_argument("--project", required=True)
    if retired:
        parser.add_argument("--reason", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    payload = {"project": parsed.project}
    if retired:
        payload["reason"] = parsed.reason
    return dispatch_and_emit(
        function_id=f"projects.{verb}",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def projects_retire(args):
    return _run(args, retired=True)


def projects_unretire(args):
    return _run(args, retired=False)
