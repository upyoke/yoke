"""Adapters for path-claim gate and activation flow commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    ensure_handlers_loaded,
    item_target,
    parse_or_usage_error,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher, emit_response
from yoke_cli.commands.adapters.project_snapshot import (
    sync_local_snapshot_for_write,
)
from yoke_contracts.api.function_call import TargetRef


CLAIMS_PATH_REQUIRED_GATE_USAGE = (
    "yoke claims path required-gate PREFIX-N [--session-id S] [--json]"
)
CLAIMS_PATH_ACTIVATION_RUN_USAGE = (
    "yoke claims path activation-run --item PREFIX-N [--session-id S] [--json]"
)
CLAIMS_PATH_BOUNDARY_PROVE_USAGE = (
    "yoke claims path boundary-prove --item PREFIX-N [--session-id S] [--json]"
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
        project=parsed.project,
        integration_target=None,
        session_id=parsed.session_id,
    )
    return dispatch_and_emit(
        function_id="claims.path.activation_run",
        target=item_target("item", parsed.item, parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def claims_path_boundary_prove(args: List[str]) -> int:
    """Observe the recorded local lane and stamp a hosted-consumable proof."""
    parser = argparse.ArgumentParser(
        prog="yoke claims path boundary-prove",
        description=CLAIMS_PATH_BOUNDARY_PROVE_USAGE,
    )
    parser.add_argument("--item", required=True, help="YOK-N or N.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CLAIMS_PATH_BOUNDARY_PROVE_USAGE)
    if parsed is None:
        return 2
    target = item_target("item", parsed.item, parsed.project)
    ensure_handlers_loaded()
    actor = build_actor(session_id=parsed.session_id)
    first = call_dispatcher(
        function_id="claims.path.boundary_context",
        target=target,
        payload={},
        actor=actor,
    )
    if not first.success:
        return emit_response(first, json_mode=parsed.json_mode)
    context = (first.result or {}).get("context") or {}
    lane = context.get("lane") or {}
    repo_path = str(lane.get("path") or "")
    if not repo_path or not Path(repo_path).is_dir():
        return _local_error(
            "boundary_lane_unreadable",
            "run this command on the machine holding the item's recorded lane",
        )
    retry = f"yoke claims path boundary-prove --item {parsed.item}"
    sync = sync_local_snapshot_for_write(
        project=str((context.get("project") or {}).get("slug") or ""),
        repo_root=repo_path,
        integration_target=None,
        session_id=parsed.session_id,
        head_only=True,
        timeout_s=None,
        retry_command=retry,
    )
    if sync["status"] != "ok":
        message = str(sync.get("message") or "lane HEAD snapshot sync failed")
        repair = str(sync.get("repair_command") or retry)
        if repair:
            message = f"{message}; retry `{repair}`"
        return _local_error("boundary_head_sync_failed", message)
    current = call_dispatcher(
        function_id="claims.path.boundary_context",
        target=target,
        payload={},
        actor=actor,
    )
    if not current.success:
        return emit_response(current, json_mode=parsed.json_mode)
    context = (current.result or {}).get("context") or {}
    observation = call_dispatcher(
        function_id="claims.path.boundary_observe",
        target=TargetRef(kind="global"),
        payload={"context": context, "repo_path": repo_path},
        actor=actor,
        local_only=True,
    )
    if not observation.success:
        return emit_response(observation, json_mode=parsed.json_mode)
    proof = (observation.result or {}).get("proof") or {}
    response = call_dispatcher(
        function_id="claims.path.boundary_prove",
        target=target,
        payload={"proof": proof},
        actor=actor,
    )
    return emit_response(
        response,
        json_mode=parsed.json_mode,
        human_writer=_write_boundary_proof,
    )


def _local_error(code: str, message: str) -> int:
    print(
        json.dumps({"success": False, "code": code, "message": message}),
        file=sys.stderr,
    )
    return 1


def _write_boundary_proof(response: Any, stdout, _stderr) -> None:
    result = response.result or {}
    print(
        "boundary-proof-recorded|"
        f"{result.get('public_ref') or result.get('item_id') or 'item'}|"
        f"{result.get('rung_id')}|"
        f"{result.get('lane_commit_sha')}",
        file=stdout,
    )


__all__ = [
    "CLAIMS_PATH_ACTIVATION_RUN_USAGE",
    "CLAIMS_PATH_BOUNDARY_PROVE_USAGE",
    "CLAIMS_PATH_REQUIRED_GATE_USAGE",
    "claims_path_activation_run",
    "claims_path_boundary_prove",
    "claims_path_required_gate",
]
