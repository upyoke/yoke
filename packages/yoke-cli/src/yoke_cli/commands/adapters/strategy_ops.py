"""``yoke strategy carry|checkpoint`` adapters."""

from __future__ import annotations

import argparse
import json
from yoke_cli.transport.human_values import write_human
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


STRATEGY_CARRY_REGISTER_NEW_USAGE = (
    "yoke strategy carry register-new --project P [--horizon-days N] "
    "[--carry-limit N] [--result-json] [--session-id S] [--json]"
)
STRATEGY_CARRY_CANDIDATE_SET_USAGE = (
    "yoke strategy carry candidate-set --project P [--horizon-days N] "
    "[--carry-limit N] [--new-ids ID ...] [--full] [--session-id S] [--json]"
)
STRATEGY_CARRY_SUMMARY_USAGE = (
    "yoke strategy carry summary --project P [--horizon-days N] "
    "[--carry-limit N] [--new-ids ID ...] [--display-limit N] [--full] "
    "[--session-id S] [--json]"
)
STRATEGY_CARRY_MARK_USAGE = (
    "yoke strategy carry mark --project P --state STATE --items ID ... "
    "[--reason TEXT] [--session-id S] [--json]"
)
STRATEGY_CHECKPOINT_RECORD_USAGE = (
    "yoke strategy checkpoint record --project P [--kind strategize|drift_review] "
    "[--session-id S] [--json]"
)
STRATEGY_CHECKPOINT_LATEST_USAGE = (
    "yoke strategy checkpoint latest --project P "
    "[--kind strategize|drift_review] [--full] [--session-id S] [--json]"
)


__all__ = [
    "strategy_carry_register_new", "strategy_carry_candidate_set",
    "strategy_carry_summary", "strategy_carry_mark", "strategy_checkpoint_record",
    "strategy_checkpoint_latest",
    "STRATEGY_CARRY_REGISTER_NEW_USAGE", "STRATEGY_CARRY_CANDIDATE_SET_USAGE",
    "STRATEGY_CARRY_SUMMARY_USAGE", "STRATEGY_CARRY_MARK_USAGE",
    "STRATEGY_CHECKPOINT_RECORD_USAGE", "STRATEGY_CHECKPOINT_LATEST_USAGE",
]


def _add_new_ids(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--new-ids", nargs="*", default=[], metavar="ID",
                        help="Item ids that register-new just added.")


def _add_project_required(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True, metavar="P", help="Project slug or id.")


def _add_carry_window(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--horizon-days", type=int, metavar="N", help="Days back to look for landings."
    )
    parser.add_argument(
        "--carry-limit", type=int, metavar="N", help="Most items to carry forward."
    )
    parser.add_argument("--now", default=None, help=argparse.SUPPRESS)


def _carry_payload(parsed: argparse.Namespace) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"project": parsed.project}
    if parsed.horizon_days is not None:
        payload["horizon_days"] = parsed.horizon_days
    if parsed.carry_limit is not None:
        payload["carry_limit"] = parsed.carry_limit
    if getattr(parsed, "now", None):
        payload["now"] = parsed.now
    return payload


def strategy_carry_register_new(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke strategy carry register-new",
        usage=STRATEGY_CARRY_REGISTER_NEW_USAGE,
    )
    _add_project_required(parser)
    _add_carry_window(parser)
    parser.add_argument(
        "--result-json", action="store_true", help="Print only the result as JSON."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRATEGY_CARRY_REGISTER_NEW_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        if parsed.result_json:
            print(json.dumps(result, default=str), file=stdout)
            return
        write_human(result, stdout)

    return dispatch_and_emit(
        function_id="strategy.carry.register_new",
        target=TargetRef(kind="global"),
        payload=_carry_payload(parsed),
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        machine_mode=parsed.result_json,
        human_writer=_human_writer,
    )


def strategy_carry_candidate_set(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke strategy carry candidate-set",
        usage=STRATEGY_CARRY_CANDIDATE_SET_USAGE,
    )
    _add_project_required(parser)
    _add_carry_window(parser)
    _add_new_ids(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRATEGY_CARRY_CANDIDATE_SET_USAGE)
    if parsed is None:
        return 2
    payload = _carry_payload(parsed)
    payload["new_ids"] = parsed.new_ids

    def _human_writer(response, stdout, stderr) -> None:
        data = (response.result or {}).get("candidate_set", {})
        write_human(data, stdout)

    return dispatch_and_emit(
        function_id="strategy.carry.candidate_set",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def strategy_carry_summary(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke strategy carry summary",
        usage=STRATEGY_CARRY_SUMMARY_USAGE,
    )
    _add_project_required(parser)
    _add_carry_window(parser)
    _add_new_ids(parser)
    parser.add_argument(
        "--display-limit", type=int, default=10, metavar="N",
        help="Most rows to print; default: 10.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRATEGY_CARRY_SUMMARY_USAGE)
    if parsed is None:
        return 2
    payload = _carry_payload(parsed)
    payload.update({"new_ids": parsed.new_ids, "display_limit": parsed.display_limit})

    def _human_writer(response, stdout, stderr) -> None:
        stdout.write(str((response.result or {}).get("summary", "")))
        stdout.write("\n")

    return dispatch_and_emit(
        function_id="strategy.carry.summary",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def strategy_carry_mark(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke strategy carry mark",
        usage=STRATEGY_CARRY_MARK_USAGE,
    )
    _add_project_required(parser)
    parser.add_argument(
        "--state", required=True, metavar="STATE", help="New carry state for the items."
    )
    parser.add_argument("--reason", metavar="TEXT", help="Why the state changes.")
    parser.add_argument(
        "--items", nargs="+", required=True, metavar="ID", help="Item ids to mark."
    )
    parser.add_argument("--now", default=None, help=argparse.SUPPRESS)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRATEGY_CARRY_MARK_USAGE)
    if parsed is None:
        return 2
    payload = {"project": parsed.project, "state": parsed.state, "items": parsed.items}
    if parsed.reason:
        payload["reason"] = parsed.reason
    if parsed.now:
        payload["now"] = parsed.now

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        print(
            f"Marked {result.get('changed', 0)} item(s) as "
            f"{result.get('state')} in project {result.get('project')}",
            file=stdout,
        )

    return dispatch_and_emit(
        function_id="strategy.carry.mark",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def _checkpoint_args(
    prog: str,
    usage: str,
    args: List[str],
) -> argparse.Namespace | None:
    parser = argparse.ArgumentParser(prog=prog, usage=usage)
    _add_project_required(parser)
    parser.add_argument(
        "--kind", default="strategize", metavar="strategize|drift_review",
        help="Checkpoint kind; default: strategize.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    return parse_or_usage_error(parser, args, usage)


def strategy_checkpoint_record(args: List[str]) -> int:
    parsed = _checkpoint_args(
        "yoke strategy checkpoint record",
        STRATEGY_CHECKPOINT_RECORD_USAGE,
        args,
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        write_human(response.result, stdout)

    return dispatch_and_emit(
        function_id="strategy.checkpoint.record",
        target=TargetRef(kind="global"),
        payload={"project": parsed.project, "kind": parsed.kind},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def strategy_checkpoint_latest(args: List[str]) -> int:
    parsed = _checkpoint_args(
        "yoke strategy checkpoint latest",
        STRATEGY_CHECKPOINT_LATEST_USAGE,
        args,
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        write_human(response.result, stdout)

    return dispatch_and_emit(
        function_id="strategy.checkpoint.latest",
        target=TargetRef(kind="global"),
        payload={"project": parsed.project, "kind": parsed.kind},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )
