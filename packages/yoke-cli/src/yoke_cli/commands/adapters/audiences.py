"""Create and list named project audiences."""

import argparse
import json

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef

USAGE_BY_FUNCTION_ID = {
    "audiences.create": "yoke audiences create --project-id N --name NAME --rules JSON [--json] [--session-id S]",
    "audiences.list": "yoke audiences list --project-id N [--json] [--session-id S]",
}


def _run(args, action):
    function_id = f"audiences.{action}"
    parser = argparse.ArgumentParser(
        prog=f"yoke audiences {action}",
        description="Named audiences select current members from actor, organization or project rules. Rules are combined with any; an audience grants no action by itself.",
    )
    parser.add_argument("--project-id", type=int, required=True)
    if action == "create":
        parser.add_argument("--name", required=True)
        parser.add_argument("--rules", type=json.loads, required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, USAGE_BY_FUNCTION_ID[function_id])
    if parsed is None:
        return 2
    payload = {"project_id": parsed.project_id}
    if action == "create":
        payload.update(name=parsed.name, rules=parsed.rules)
    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def create(args):
    return _run(args, "create")


def list_audiences(args):
    return _run(args, "list")
