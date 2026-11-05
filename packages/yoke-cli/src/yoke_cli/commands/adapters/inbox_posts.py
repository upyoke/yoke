"""Create durable audience-addressed posts and mark shared work Done."""

import argparse
import json
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef

USAGE_BY_FUNCTION_ID = {
    "inbox.posts.create": "yoke inbox posts create --project-id N --title TEXT --body TEXT --source TEXT (--audience-id N | --audience-name NAME | --rules JSON) [--fields JSON] [--json] [--session-id S]",
    "inbox.posts.done": "yoke inbox posts done POST_ID [--json] [--session-id S]",
}


def create(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke inbox posts create",
        description="Post shared work to a live audience. Creating requires the project's items.write permission; any addressed reader may mark it Done for everyone.",
    )
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--source", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--audience-id", type=int)
    group.add_argument("--audience-name")
    group.add_argument(
        "--rules",
        type=json.loads,
        help="JSON rule array: scope_kind, scope_id, optional role_name.",
    )
    parser.add_argument("--fields", type=json.loads, default={})
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, USAGE_BY_FUNCTION_ID["inbox.posts.create"]
    )
    if parsed is None:
        return 2
    payload = {
        key: getattr(parsed, key)
        for key in (
            "project_id",
            "title",
            "body",
            "source",
            "fields",
            "audience_id",
            "audience_name",
            "rules",
        )
        if getattr(parsed, key) is not None
    }
    return dispatch_and_emit(
        function_id="inbox.posts.create",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def done(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke inbox posts done",
        description="Mark an addressed post Done for everyone. Repeated calls report the first person and time.",
    )
    parser.add_argument("post_id", type=int)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, USAGE_BY_FUNCTION_ID["inbox.posts.done"]
    )
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="inbox.posts.done",
        target=TargetRef(kind="global"),
        payload={"post_id": parsed.post_id},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
