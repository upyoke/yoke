"""CLI adapter for a steering-authorized stage private-route proof."""

from __future__ import annotations

import argparse
from typing import Any, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.session_execution import is_subagent_execution


QUALIFICATION_OPEN_USAGE = (
    "yoke session-control qualification open --project P --release-sha SHA "
    "--run-id RUN --surface SURFACE --version V --operation OP "
    "--route (direct | broker | hook) [--session-id S] [--json]"
)


def _write_grant(response: Any, stdout, _stderr) -> None:
    grant = (response.result or {}).get("grant") or {}
    print(
        "qualification "
        f"lease={grant.get('lease_id', '')} "
        f"digest={grant.get('grant_digest', '')} "
        f"expires={grant.get('expires_at', '')}",
        file=stdout,
    )


def session_qualification_open(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke session-control qualification open",
        usage=QUALIFICATION_OPEN_USAGE,
    )
    parser.add_argument(
        "--project", required=True, metavar="P", help="Project the grant covers."
    )
    parser.add_argument(
        "--release-sha",
        required=True,
        metavar="SHA",
        help="Full commit SHA being qualified.",
    )
    parser.add_argument(
        "--run-id",
        required=True,
        dest="acceptance_run_id",
        metavar="RUN",
        help="Acceptance run this grant belongs to.",
    )
    parser.add_argument(
        "--surface", required=True, metavar="SURFACE", help="Surface being qualified."
    )
    parser.add_argument(
        "--version", required=True, metavar="V", help="Surface version qualified."
    )
    parser.add_argument(
        "--operation", required=True, metavar="OP", help="Operation being qualified."
    )
    parser.add_argument(
        "--route",
        required=True,
        choices=("direct", "broker", "hook"),
        help="How the operation reaches the session.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QUALIFICATION_OPEN_USAGE)
    if parsed is None:
        return 2
    if is_subagent_execution():
        return usage_error(
            "in-process subagents cannot open Fleet qualification grants; "
            "return to the top-level session holding the covering steering seat"
        )
    return dispatch_and_emit(
        function_id="session_control.qualification.open",
        target=TargetRef(kind="global"),
        payload={
            "project": parsed.project,
            "environment": "stage",
            "release_sha": parsed.release_sha,
            "acceptance_run_id": parsed.acceptance_run_id,
            "surface": parsed.surface,
            "version": parsed.version,
            "operation": parsed.operation,
            "route": parsed.route,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_grant,
    )


__all__ = ["QUALIFICATION_OPEN_USAGE", "session_qualification_open"]
