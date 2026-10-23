"""Sourced model catalog lookup, review, and publication adapters."""

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
DIFF_FUNCTION_ID = "models.diff.run"
PUBLISH_FUNCTION_ID = "models.publish.run"
REVISIONS_FUNCTION_ID = "models.revisions.run"
RESTORE_FUNCTION_ID = "models.restore.run"
LOOKUP_USAGE = (
    "yoke models lookup MODEL_ID [--at UTC] [--full] [--session-id S] [--json]"
)
GET_USAGE = (
    "yoke models get [--model-id MODEL_ID] [--revision-id REV | --at UTC] "
    "[--full] [--session-id S] [--json]"
)
VALIDATE_USAGE = "yoke models validate --stdin [--full] [--session-id S] [--json]"
DIFF_USAGE = "yoke models diff --stdin [--full] [--session-id S] [--json]"
PUBLISH_USAGE = (
    "yoke models publish --stdin --expected-base REV --source-note TEXT "
    "[--effective-at UTC] [--session-id S] [--json]"
)
REVISIONS_USAGE = "yoke models revisions [--full] [--session-id S] [--json]"
RESTORE_USAGE = (
    "yoke models restore REV --expected-base REV --source-note TEXT "
    "[--effective-at UTC] [--session-id S] [--json]"
)


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
    efforts = ",".join(record.get("reasoning_efforts") or ()) or "unpublished"
    windows = record.get("context_window_tokens") or ()
    context = ",".join(str(n) for n in windows) or "unpublished"
    price = record.get("api_price") or {}
    estimated = price.get("estimated_fields") or ()
    print(
        f"{record.get('model_id')} efforts={efforts} context={context} "
        f"replacement={record.get('replacement_model_id') or '-'} "
        f"input={price.get('input_per_million_usd')} "
        f"output={price.get('output_per_million_usd')} "
        f"estimated={','.join(estimated) if estimated else '-'}",
        file=stdout,
    )


def models_lookup(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke models lookup", usage=LOOKUP_USAGE
    )
    parser.add_argument(
        "model_id", help="Launch --model string, including effort suffixes."
    )
    parser.add_argument(
        "--at", metavar="UTC", help="Read the catalog as it was at this UTC time."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, LOOKUP_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id=LOOKUP_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload={
            "model_id": parsed.model_id,
            **({"at": parsed.at} if parsed.at else {}),
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=None if parsed.json_mode else _print_lookup,
    )


def models_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke models get", usage=GET_USAGE)
    parser.add_argument(
        "--model-id", default=None, help="Show only this model's record."
    )
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument(
        "--revision-id", metavar="REV", help="Read this one saved catalog revision."
    )
    selector.add_argument(
        "--at", metavar="UTC", help="Read the catalog as it was at this UTC time."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GET_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, str] = {}
    if parsed.model_id:
        payload["model_id"] = parsed.model_id
    if parsed.revision_id:
        payload["revision_id"] = parsed.revision_id
    if parsed.at:
        payload["at"] = parsed.at
    return dispatch_and_emit(
        function_id=GET_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def models_validate(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke models validate", usage=VALIDATE_USAGE
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


def _catalog_from_stdin() -> list[dict[str, Any]] | None:
    try:
        candidate = json.loads(sys.stdin.read())
    except json.JSONDecodeError as exc:
        usage_error(f"model catalog stdin is not JSON: {exc}")
        return None
    if not isinstance(candidate, list) or not all(
        isinstance(record, dict) for record in candidate
    ):
        usage_error("model catalog stdin must be a JSON list of record objects")
        return None
    return candidate


def models_diff(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke models diff", usage=DIFF_USAGE)
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read the full proposed catalog, a JSON list of records, from stdin.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DIFF_USAGE)
    if parsed is None:
        return 2
    if not parsed.stdin:
        return usage_error("models diff requires --stdin")
    catalog = _catalog_from_stdin()
    if catalog is None:
        return 2
    return dispatch_and_emit(
        function_id=DIFF_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload={"catalog": catalog},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def models_publish(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke models publish", usage=PUBLISH_USAGE
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read the full new catalog, a JSON list of records, from stdin.",
    )
    parser.add_argument(
        "--expected-base",
        required=True,
        metavar="REV",
        help="The current revision you diffed against; the write fails if it moved.",
    )
    parser.add_argument(
        "--source-note",
        required=True,
        metavar="TEXT",
        help="Where the new data came from and why it is being published.",
    )
    parser.add_argument(
        "--effective-at",
        metavar="UTC",
        help="Future ISO-8601 UTC time the catalog takes effect (default: now).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PUBLISH_USAGE)
    if parsed is None:
        return 2
    if not parsed.stdin:
        return usage_error("models publish requires --stdin")
    catalog = _catalog_from_stdin()
    if catalog is None:
        return 2
    return dispatch_and_emit(
        function_id=PUBLISH_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload={
            "catalog": catalog,
            "expected_base_revision_id": parsed.expected_base,
            "source_note": parsed.source_note,
            "effective_at": parsed.effective_at,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def models_revisions(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke models revisions", usage=REVISIONS_USAGE
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, REVISIONS_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id=REVISIONS_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def models_restore(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke models restore", usage=RESTORE_USAGE
    )
    parser.add_argument(
        "revision_id",
        metavar="REV",
        help="The saved revision whose whole catalog becomes current again.",
    )
    parser.add_argument(
        "--expected-base",
        required=True,
        metavar="REV",
        help="The current revision; the restore fails if it moved.",
    )
    parser.add_argument(
        "--source-note",
        required=True,
        metavar="TEXT",
        help="Why the old revision is being restored, with evidence.",
    )
    parser.add_argument(
        "--effective-at",
        metavar="UTC",
        help="Future ISO-8601 UTC time the restore takes effect (default: now).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, RESTORE_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id=RESTORE_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload={
            "source_revision_id": parsed.revision_id,
            "expected_base_revision_id": parsed.expected_base,
            "source_note": parsed.source_note,
            "effective_at": parsed.effective_at,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


USAGE_BY_FUNCTION_ID = {
    LOOKUP_FUNCTION_ID: LOOKUP_USAGE,
    GET_FUNCTION_ID: GET_USAGE,
    VALIDATE_FUNCTION_ID: VALIDATE_USAGE,
    DIFF_FUNCTION_ID: DIFF_USAGE,
    PUBLISH_FUNCTION_ID: PUBLISH_USAGE,
    REVISIONS_FUNCTION_ID: REVISIONS_USAGE,
    RESTORE_FUNCTION_ID: RESTORE_USAGE,
}

__all__ = [
    "GET_USAGE",
    "LOOKUP_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "VALIDATE_USAGE",
    "models_get",
    "models_lookup",
    "models_validate",
    "models_diff",
    "models_publish",
    "models_revisions",
    "models_restore",
]
