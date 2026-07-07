"""``yoke strategy carry|checkpoint|master-plan-check`` adapters."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher, emit_response
from yoke_contracts.api.function_call import TargetRef


STRATEGY_CARRY_REGISTER_NEW_USAGE = (
    "yoke strategy carry register-new --project P [--horizon-days N] "
    "[--carry-limit N] [--result-json] [--session-id S] [--json]"
)
STRATEGY_CARRY_CANDIDATE_SET_USAGE = (
    "yoke strategy carry candidate-set --project P [--horizon-days N] "
    "[--carry-limit N] [--new-ids ID ...] [--pretty] [--session-id S] [--json]"
)
STRATEGY_CARRY_SUMMARY_USAGE = (
    "yoke strategy carry summary --project P [--horizon-days N] "
    "[--carry-limit N] [--new-ids ID ...] [--display-limit N] "
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
    "yoke strategy checkpoint latest --project P [--session-id S] [--json]"
)
STRATEGY_MASTER_PLAN_CHECK_USAGE = (
    "yoke strategy master-plan-check [--plan-path PATH] "
    "[--exit-nonzero-on-drift] [--session-id S] [--json]"
)


__all__ = [
    "strategy_carry_register_new",
    "strategy_carry_candidate_set",
    "strategy_carry_summary",
    "strategy_carry_mark",
    "strategy_checkpoint_record",
    "strategy_checkpoint_latest",
    "strategy_master_plan_check",
    "STRATEGY_CARRY_REGISTER_NEW_USAGE",
    "STRATEGY_CARRY_CANDIDATE_SET_USAGE",
    "STRATEGY_CARRY_SUMMARY_USAGE",
    "STRATEGY_CARRY_MARK_USAGE",
    "STRATEGY_CHECKPOINT_RECORD_USAGE",
    "STRATEGY_CHECKPOINT_LATEST_USAGE",
    "STRATEGY_MASTER_PLAN_CHECK_USAGE",
]


def _add_project_required(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True)


def _add_carry_window(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--horizon-days", type=int, default=None)
    parser.add_argument("--carry-limit", type=int, default=None)
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
        description=STRATEGY_CARRY_REGISTER_NEW_USAGE,
    )
    _add_project_required(parser)
    _add_carry_window(parser)
    parser.add_argument("--result-json", action="store_true")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, STRATEGY_CARRY_REGISTER_NEW_USAGE,
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        if parsed.result_json:
            print(json.dumps(result, sort_keys=True), file=stdout)
            return
        for item_id in result.get("new_ids", []):
            print(f"YOK-{item_id}", file=stdout)

    return dispatch_and_emit(
        function_id="strategy.carry.register_new",
        target=TargetRef(kind="global"),
        payload=_carry_payload(parsed),
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def strategy_carry_candidate_set(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke strategy carry candidate-set",
        description=STRATEGY_CARRY_CANDIDATE_SET_USAGE,
    )
    _add_project_required(parser)
    _add_carry_window(parser)
    parser.add_argument("--new-ids", nargs="*", default=[])
    parser.add_argument("--pretty", action="store_true")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, STRATEGY_CARRY_CANDIDATE_SET_USAGE,
    )
    if parsed is None:
        return 2
    payload = _carry_payload(parsed)
    payload["new_ids"] = parsed.new_ids

    def _human_writer(response, stdout, stderr) -> None:
        data = (response.result or {}).get("candidate_set", {})
        print(
            json.dumps(data, indent=2 if parsed.pretty else None, sort_keys=True),
            file=stdout,
        )

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
        description=STRATEGY_CARRY_SUMMARY_USAGE,
    )
    _add_project_required(parser)
    _add_carry_window(parser)
    parser.add_argument("--new-ids", nargs="*", default=[])
    parser.add_argument("--display-limit", type=int, default=10)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRATEGY_CARRY_SUMMARY_USAGE)
    if parsed is None:
        return 2
    payload = _carry_payload(parsed)
    payload.update(
        {
            "new_ids": parsed.new_ids,
            "display_limit": parsed.display_limit,
        }
    )

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
        description=STRATEGY_CARRY_MARK_USAGE,
    )
    _add_project_required(parser)
    parser.add_argument("--state", required=True)
    parser.add_argument("--reason")
    parser.add_argument("--items", nargs="+", required=True)
    parser.add_argument("--now", default=None, help=argparse.SUPPRESS)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRATEGY_CARRY_MARK_USAGE)
    if parsed is None:
        return 2
    payload = {
        "project": parsed.project,
        "state": parsed.state,
        "items": parsed.items,
    }
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
    prog: str, usage: str, args: List[str],
) -> argparse.Namespace | None:
    parser = argparse.ArgumentParser(prog=prog, description=usage)
    _add_project_required(parser)
    parser.add_argument("--kind", default="strategize")
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
        result = response.result or {}
        print(
            f"Recorded {result.get('kind')} checkpoint for project "
            f"{result.get('project')}",
            file=stdout,
        )

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
        latest = (response.result or {}).get("latest")
        if latest:
            print(latest, file=stdout)

    return dispatch_and_emit(
        function_id="strategy.checkpoint.latest",
        target=TargetRef(kind="global"),
        payload={"project": parsed.project, "kind": parsed.kind},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def _default_master_plan_path() -> Path:
    workspace = Path(os.environ.get("YOKE_REPO_ROOT") or os.getcwd())
    return (workspace / ".yoke" / "strategy" / "MASTER-PLAN.md").resolve()


def strategy_master_plan_check(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke strategy master-plan-check",
        description=STRATEGY_MASTER_PLAN_CHECK_USAGE,
    )
    parser.add_argument("--plan-path")
    parser.add_argument("--exit-nonzero-on-drift", action="store_true")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, STRATEGY_MASTER_PLAN_CHECK_USAGE,
    )
    if parsed is None:
        return 2
    plan_path = Path(parsed.plan_path).resolve() if parsed.plan_path else _default_master_plan_path()
    if not plan_path.exists():
        return usage_error(f"MASTER-PLAN.md not found at {plan_path}")
    markdown = plan_path.read_text(encoding="utf-8")
    from yoke_cli.commands import _helpers as _helpers

    _helpers.ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="strategy.master_plan_check.run",
        target=TargetRef(kind="global"),
        payload={"markdown": markdown},
        actor=build_actor(session_id=parsed.session_id),
    )

    def _human_writer(human_response, stdout, stderr) -> None:
        stdout.write(str((human_response.result or {}).get("markdown_report", "")))

    rc = emit_response(
        response, json_mode=parsed.json_mode, human_writer=_human_writer,
    )
    if (
        rc == 0
        and parsed.exit_nonzero_on_drift
        and int((response.result or {}).get("contradiction_count", 0)) > 0
    ):
        return 1
    return rc
