"""Create, list and revoke the signed-in person's personal API tokens."""

import argparse

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.admission_floor_recovery import admission_floor_hint
from yoke_contracts.api.function_call import TargetRef

CREATE_USAGE = "yoke tokens create --name LABEL [--json]"
LIST_USAGE = "yoke tokens list [--json]"
REVOKE_USAGE = "yoke tokens revoke TOKEN-ID [--json]"
USAGE_BY_FUNCTION_ID = {
    "profile.token.create": CREATE_USAGE,
    "profile.get": LIST_USAGE,
    "profile.token.revoke": REVOKE_USAGE,
}


def _created(response, stdout, stderr):
    result = response.result
    print(
        f"Token {result['token_id']} ({result['name']}). Copy it now; shown once:",
        file=stdout,
    )
    print(result["raw_token"], file=stdout)
    print("Lost it? Revoke it and create a new one.", file=stdout)


def _listed(response, stdout, stderr):
    tokens = response.result["tokens"]
    if not tokens:
        print("No tokens yet.", file=stdout)
        return
    print("ID\tName\tCreated\tLast used\tStatus", file=stdout)
    for token in tokens:
        print(
            f"{token['token_id']}\t{token['name']}\t{token['created_at'] or '—'}\t"
            f"{token['last_used_at'] or 'never'}\t{token['status']}",
            file=stdout,
        )


def _revoked(response, stdout, stderr):
    print(f"Revoked token {response.result['token_id']}.", file=stdout)


def _run(args, action, function_id, writer):
    parser = argparse.ArgumentParser(
        prog=f"yoke tokens {action}",
        description=(
            "Manage your own API tokens on the active connection. "
            "No project or harness session is needed. "
            "Copy a new token now; it is shown once. Lost it? Run yoke tokens list, "
            "revoke its ID with yoke tokens revoke TOKEN-ID, then create a new one."
        ),
    )
    if action == "create":
        parser.add_argument(
            "--name", required=True, help="Token label (1–80 characters)"
        )
    elif action == "revoke":
        parser.add_argument(
            "token_id", type=int, metavar="TOKEN-ID", help="ID from yoke tokens list"
        )
    add_json_arg(parser)
    add_session_arg(parser)
    parsed = parse_or_usage_error(parser, args, USAGE_BY_FUNCTION_ID[function_id])
    if parsed is None:
        return 2
    payload = {}
    if action == "create":
        payload["name"] = parsed.name
    elif action == "revoke":
        payload["token_id"] = parsed.token_id
    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=writer,
        function_hint=admission_floor_hint,
    )


def tokens_create(args):
    return _run(args, "create", "profile.token.create", _created)


def tokens_list(args):
    return _run(args, "list", "profile.get", _listed)


def tokens_revoke(args):
    return _run(args, "revoke", "profile.token.revoke", _revoked)
