"""Argument parsing for ``yoke claims path register``."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    parse_or_usage_error,
    split_comma,
    usage_error,
)


CLAIM_PATH_REGISTER_USAGE = (
    "yoke claims path register --item PREFIX-N [--paths PATH1,PATH2,...] "
    "[--task-num N] "
    "[--mode exclusive|exception] [--exception-reason TEXT] [--allow-planned] "
    "[--tentative-paths PATH1,PATH2,...] "
    "[--integration-target NAME] [--session-id S] [--json]"
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
        description=CLAIM_PATH_REGISTER_USAGE,
    )
    parser.add_argument(
        "--item",
        required=True,
        help="Item id (PREFIX-N or project-local number).",
    )
    parser.add_argument(
        "--task-num",
        type=int,
        default=None,
        help="Generated Epic task scope for required-per-task workflows.",
    )
    parser.add_argument(
        "--paths",
        default=None,
        help="Comma-separated paths required in exclusive mode.",
    )
    parser.add_argument(
        "--mode",
        choices=("exclusive", "exception"),
        default="exclusive",
    )
    parser.add_argument(
        "--exception-reason",
        default=None,
        help="Required justification in exception mode.",
    )
    parser.add_argument(
        "--allow-planned",
        action="store_true",
        help="Permit claim registration for not-yet-committed paths.",
    )
    parser.add_argument(
        "--tentative-paths",
        default="",
        help="Subset of --paths to mint as materialization_state=tentative.",
    )
    parser.add_argument(
        "--integration-target",
        default=None,
        help="Override integration target classification (advanced).",
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
