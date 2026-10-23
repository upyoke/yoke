"""Argument parsing for ``yoke claims path register``."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    parse_or_usage_error,
    split_comma,
    usage_error,
)
from yoke_contracts.claim_path_syntax import claim_path_refusal
from yoke_cli.commands.adapters.claims_path_unmaterialized import (
    UNMATERIALIZED_PATH_REFUSAL,
    unmaterialized_paths,
)


CLAIM_PATH_REGISTER_USAGE = (
    "yoke claims path register --item PREFIX-N [--paths PATH1,PATH2,...] "
    "[--task-num N] "
    "[--mode exclusive|exception] [--exception-reason TEXT] [--allow-planned] "
    "[--tentative-paths PATH1,PATH2,...] "
    "[--integration-target NAME] [--project P] [--session-id S] [--json]"
)


@dataclass(frozen=True)
class PathRegisterArguments:
    """Validated registration arguments and their function payload."""

    parsed: argparse.Namespace
    payload: Dict[str, Any]


def parse_path_register_args(args: List[str]) -> PathRegisterArguments | int:
    """Parse and validate path-registration flags.

    Integer returns are CLI exit codes for usage failures.
    """
    parser = argparse.ArgumentParser(
        prog="yoke claims path register",
        usage=CLAIM_PATH_REGISTER_USAGE,
    )
    parser.add_argument(
        "--item",
        required=True,
        metavar="PREFIX-N",
        help="Item the claim is for.",
    )
    parser.add_argument(
        "--task-num",
        type=int,
        default=None,
        metavar="N",
        help="Epic task the claim covers, for workflows that claim per task.",
    )
    parser.add_argument(
        "--paths",
        default=None,
        metavar="PATH1,PATH2,...",
        help="Comma-separated paths to claim; required in exclusive mode.",
    )
    parser.add_argument(
        "--mode",
        choices=("exclusive", "exception"),
        default="exclusive",
        help="exclusive claims the listed paths; exception claims no paths and "
        "needs --exception-reason (default: exclusive).",
    )
    parser.add_argument(
        "--exception-reason",
        default=None,
        metavar="TEXT",
        help="Why no paths are claimed; required in exception mode.",
    )
    parser.add_argument(
        "--allow-planned",
        action="store_true",
        help="Allow paths that are not committed yet.",
    )
    parser.add_argument(
        "--tentative-paths",
        default="",
        metavar="PATH1,PATH2,...",
        help="Which --paths you might not touch after all; needs --allow-planned.",
    )
    parser.add_argument(
        "--integration-target",
        default=None,
        metavar="NAME",
        help="Branch the work merges into (default: worked out from the item).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CLAIM_PATH_REGISTER_USAGE)
    if parsed is None:
        return 2

    paths = split_comma(parsed.paths or "")
    tentative_paths = split_comma(parsed.tentative_paths or "")
    if parsed.mode == "exclusive" and not paths:
        return usage_error("--paths is required in exclusive mode")
    if parsed.mode == "exclusive" and parsed.exception_reason:
        return usage_error("--exception-reason requires --mode exception")
    if parsed.mode == "exception" and paths:
        return usage_error("--paths is not accepted in exception mode")
    if parsed.mode == "exception" and not (parsed.exception_reason or "").strip():
        return usage_error("--exception-reason is required in exception mode")
    if parsed.task_num is not None and parsed.task_num < 1:
        return usage_error("--task-num must be a positive integer")
    if tentative_paths and not parsed.allow_planned:
        return usage_error("--tentative-paths requires --allow-planned")
    if not set(tentative_paths).issubset(set(paths)):
        return usage_error("--tentative-paths must be a subset of --paths")
    # Refuse here rather than after a whole-tree snapshot scan and a relay
    # round trip that can spend minutes retrying without printing anything.
    refusal = claim_path_refusal(paths)
    if refusal is not None:
        code, message = refusal
        print(
            json.dumps({"success": False, "code": code, "message": message}),
            file=sys.stderr,
        )
        return 2
    if parsed.mode == "exclusive" and not parsed.allow_planned:
        unmaterialized = unmaterialized_paths(paths)
        if unmaterialized:
            return usage_error(
                UNMATERIALIZED_PATH_REFUSAL.format(paths=", ".join(unmaterialized))
            )

    payload: Dict[str, Any] = {
        "paths": paths,
        "mode": parsed.mode,
        "allow_planned": bool(parsed.allow_planned),
    }
    if parsed.task_num is not None:
        payload["task_num"] = parsed.task_num
    if parsed.exception_reason:
        payload["exception_reason"] = parsed.exception_reason
    if parsed.integration_target:
        payload["integration_target"] = parsed.integration_target
    if tentative_paths:
        payload["tentative_paths"] = tentative_paths
    return PathRegisterArguments(parsed=parsed, payload=payload)


__all__ = [
    "CLAIM_PATH_REGISTER_USAGE",
    "PathRegisterArguments",
    "parse_path_register_args",
]
