"""``yoke models lookup|get|validate`` adapters."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, TextIO

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


LOOKUP_FUNCTION_ID = "models.lookup.run"
GET_FUNCTION_ID = "models.get.run"
VALIDATE_FUNCTION_ID = "models.validate.run"
LOOKUP_USAGE = "yoke models lookup MODEL_ID [--json]"
GET_USAGE = "yoke models get [--model-id MODEL_ID] [--json]"
VALIDATE_USAGE = "yoke models validate --stdin [--json]"


def _print_lookup(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    if not response.success:
        message = response.error.message if response.error else "models lookup failed"
        print(message, file=stderr)
        return
    result = response.result or {}
    researched = result.get("researched")
    record = result.get("record")
    if not researched or not isinstance(record, dict):
        print(f"{result.get('model_id', '')} researched=false", file=stdout)
        return
    tier = record.get("proposed_tier") or "unclassified"
    price = record.get("api_price") or {}
    estimated = price.get("estimated_fields") or ()
    print(
        f"{record.get('model_id')} tier={tier} "
        f"replacement={record.get('replacement_model_id') or '-'} "
        f"input={price.get('input_per_million_usd')} "
        f"output={price.get('output_per_million_usd')} "
        f"estimated={','.join(estimated) if estimated else '-'}",
        file=stdout,
    )


def models_lookup(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke models lookup", description=LOOKUP_USAGE
    )
    parser.add_argument(
        "model_id", help="Launch --model string, including effort suffixes."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, LOOKUP_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id=LOOKUP_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload={"model_id": parsed.model_id},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=None if parsed.json_mode else _print_lookup,
    )


def models_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke models get", description=GET_USAGE)
    parser.add_argument("--model-id", default=None, help="Optional single-id lookup.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GET_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, str] = {}
    if parsed.model_id:
        payload["model_id"] = parsed.model_id
    return dispatch_and_emit(
        function_id=GET_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def models_validate(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke models validate", description=VALIDATE_USAGE
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read one proposed record JSON object from stdin.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, VALIDATE_USAGE)
    if parsed is None:
        return 2
    if not parsed.stdin:
        return usage_error("models validate requires --stdin")
    try:
        record = json.loads(sys.stdin.read())
    except json.JSONDecodeError as exc:
        return usage_error(f"models validate stdin is not JSON: {exc}")
    if not isinstance(record, dict):
        return usage_error("models validate stdin must be one JSON object")
    return dispatch_and_emit(
        function_id=VALIDATE_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload={"record": record},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


USAGE_BY_FUNCTION_ID = {
    LOOKUP_FUNCTION_ID: LOOKUP_USAGE,
    GET_FUNCTION_ID: GET_USAGE,
    VALIDATE_FUNCTION_ID: VALIDATE_USAGE,
}

__all__ = [
    "GET_USAGE",
    "LOOKUP_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "VALIDATE_USAGE",
    "models_get",
    "models_lookup",
    "models_validate",
]
