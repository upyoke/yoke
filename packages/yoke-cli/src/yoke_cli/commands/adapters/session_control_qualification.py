"""CLI adapter for an operator-opened stage private-route proof."""

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
    "--run-id RUN --surface S --version V --operation OP --route ROUTE [--json]"
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
        description=QUALIFICATION_OPEN_USAGE,
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--run-id", required=True, dest="acceptance_run_id")
    parser.add_argument("--surface", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--operation", required=True)
    parser.add_argument("--route", required=True, choices=("direct", "broker", "hook"))
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QUALIFICATION_OPEN_USAGE)
    if parsed is None:
        return 2
    if is_subagent_execution():
        return usage_error(
            "in-process subagents cannot open Fleet qualification grants; "
            "return to the top-level operator session"
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
