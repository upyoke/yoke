"""``yoke readiness ...`` adapters."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    ensure_handlers_loaded,
    item_target,
    parse_or_usage_error,
)
from yoke_cli.transport.dispatcher import (
    build_actor,
    call_dispatcher,
    response_to_dict,
)
from yoke_contracts.api.function_call import FunctionCallResponse


READINESS_CHECK_USAGE = (
    "yoke readiness check PREFIX-N [--skip-readiness-check] "
    "[--session-id S] [--json]"
)
READINESS_PRD_VALIDATE_USAGE = (
    "yoke readiness prd-validate PREFIX-N [--strict] "
    "[--session-id S] [--json]"
)
READINESS_REPAIR_STALE_COUNT_USAGE = (
    "yoke readiness repair-stale-count --item PREFIX-N "
    "[--session-id S] [--json]"
)
READINESS_REPAIR_CLAIM_COVERAGE_USAGE = (
    "yoke readiness repair-claim-coverage --item PREFIX-N "
    "[--session-id S] [--json]"
)


def readiness_check(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke readiness check",
        description=READINESS_CHECK_USAGE,
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
    parser.add_argument(
        "--skip-readiness-check",
        action="store_true",
        help="Operator override for the idea-time advisory check.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, READINESS_CHECK_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.skip_readiness_check:
        payload["skip_readiness_check"] = True
    return dispatch_and_emit(
        function_id="readiness.check.run",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def readiness_prd_validate(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke readiness prd-validate",
        description=READINESS_PRD_VALIDATE_USAGE,
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as validation failure.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, READINESS_PRD_VALIDATE_USAGE)
    if parsed is None:
        return 2
    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="readiness.prd_validate.run",
        target=item_target("item", parsed.item, parsed.project),
        payload={"strict": bool(parsed.strict)},
        actor=build_actor(session_id=parsed.session_id),
    )
    return _emit_prd_validate(response, json_mode=parsed.json_mode)


def _emit_prd_validate(
    response: FunctionCallResponse,
    *,
    json_mode: bool,
) -> int:
    if json_mode:
        print(json.dumps(response_to_dict(response), sort_keys=True))
        return 0 if response.success else 1
    report_text = str((response.result or {}).get("report_text") or "").strip()
    if report_text:
        print(report_text)
        return 0 if response.success else 1
    if response.success:
        print(json.dumps(response.result, sort_keys=True))
        return 0
    if response.error is not None:
        print(
            f"error ({response.error.code}): {response.error.message}",
            file=sys.stderr,
        )
        if response.error.recovery_hint:
            print(f"hint: {response.error.recovery_hint}", file=sys.stderr)
    else:
        print("error: dispatch returned success=False", file=sys.stderr)
    return 0 if response.success else 1


def readiness_repair_stale_count(args: List[str]) -> int:
    return _repair(
        args,
        prog="yoke readiness repair-stale-count",
        usage=READINESS_REPAIR_STALE_COUNT_USAGE,
        function_id="readiness.repair_stale_count",
    )


def readiness_repair_claim_coverage(args: List[str]) -> int:
    return _repair(
        args,
        prog="yoke readiness repair-claim-coverage",
        usage=READINESS_REPAIR_CLAIM_COVERAGE_USAGE,
        function_id="readiness.repair_claim_coverage",
    )


def _repair(
    args: List[str],
    *,
    prog: str,
    usage: str,
    function_id: str,
) -> int:
    parser = argparse.ArgumentParser(prog=prog, description=usage)
    parser.add_argument("--item", required=True, help="YOK-N or N.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id=function_id,
        target=item_target("item", parsed.item, parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "READINESS_CHECK_USAGE",
    "READINESS_PRD_VALIDATE_USAGE",
    "READINESS_REPAIR_CLAIM_COVERAGE_USAGE",
    "READINESS_REPAIR_STALE_COUNT_USAGE",
    "readiness_check",
    "readiness_prd_validate",
    "readiness_repair_claim_coverage",
    "readiness_repair_stale_count",
]
