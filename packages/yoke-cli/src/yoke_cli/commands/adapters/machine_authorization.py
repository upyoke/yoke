"""Personal device-code read and approval adapters."""

import argparse
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef

USAGE_BY_FUNCTION_ID = {
    "machine_authorization.get": "yoke machine-authorization get CODE [--json]",
    "machine_authorization.resolve": "yoke machine-authorization resolve CODE --action approve|deny [--json]",
}


def _call(args, *, resolve=False):
    function_id = (
        "machine_authorization.resolve" if resolve else "machine_authorization.get"
    )
    usage = USAGE_BY_FUNCTION_ID[function_id]
    parser = argparse.ArgumentParser(
        prog=usage.split(" CODE")[0],
        description="Read a device code or approve your own machine as the signed-in actor.",
    )
    parser.add_argument("code")
    if resolve:
        parser.add_argument("--action", required=True, choices=("approve", "deny"))
    add_json_arg(parser)
    add_session_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    payload = {"code": parsed.code}
    if resolve:
        payload["action"] = parsed.action
    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def authorization_get(args):
    return _call(args)


def authorization_resolve(args):
    return _call(args, resolve=True)
