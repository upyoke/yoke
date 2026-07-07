"""Adapters for path-claim gate and activation flow commands."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.project_snapshot import (
    sync_local_snapshot_for_write,
)


CLAIMS_PATH_REQUIRED_GATE_USAGE = (
    "yoke claims path required-gate PREFIX-N [--session-id S] [--json]"
)
CLAIMS_PATH_ACTIVATION_RUN_USAGE = (
    "yoke claims path activation-run --item PREFIX-N "
    "[--session-id S] [--json]"
)


def claims_path_required_gate(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims path required-gate",
        description=CLAIMS_PATH_REQUIRED_GATE_USAGE,
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CLAIMS_PATH_REQUIRED_GATE_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="claims.path.required_gate",
        target=item_target("item", parsed.item, parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def claims_path_activation_run(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims path activation-run",
        description=CLAIMS_PATH_ACTIVATION_RUN_USAGE,
    )
    parser.add_argument("--item", required=True, help="YOK-N or N.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CLAIMS_PATH_ACTIVATION_RUN_USAGE)
    if parsed is None:
        return 2
    sync_local_snapshot_for_write(
        project=parsed.project, integration_target=None,
        session_id=parsed.session_id,
    )
    return dispatch_and_emit(
        function_id="claims.path.activation_run",
        target=item_target("item", parsed.item, parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "CLAIMS_PATH_ACTIVATION_RUN_USAGE",
    "CLAIMS_PATH_REQUIRED_GATE_USAGE",
    "claims_path_activation_run",
    "claims_path_required_gate",
]
