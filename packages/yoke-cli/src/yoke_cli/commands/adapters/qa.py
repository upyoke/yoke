"""``yoke qa ...`` write flag adapters."""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List, TextIO

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.api.function_call import FunctionCallResponse


__all__ = [
    "qa_requirement_update", "qa_requirement_waive",
    "qa_run_record_verdict",
    "qa_requirement_auto_create_for_item",
    "QA_REQUIREMENT_UPDATE_USAGE", "QA_REQUIREMENT_WAIVE_USAGE",
    "QA_RUN_RECORD_VERDICT_USAGE",
    "QA_REQUIREMENT_AUTO_CREATE_FOR_ITEM_USAGE",
    "USAGE_BY_FUNCTION_ID",
]


QA_REQUIREMENT_UPDATE_USAGE = (
    "yoke qa requirement update --requirement-id N --field FIELD "
    "(--value VALUE | --null) [--session-id S] [--json]"
)


def qa_requirement_update(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa requirement update", description=QA_REQUIREMENT_UPDATE_USAGE,
    )
    parser.add_argument("--requirement-id", dest="requirement_id",
                        type=int, required=True,
                        help="Target qa_requirements.id.")
    parser.add_argument("--field", required=True,
                        help="Updatable field name.")
    value_group = parser.add_mutually_exclusive_group(required=True)
    value_group.add_argument("--value", default=None,
                             help="New value (string).")
    value_group.add_argument("--null", action="store_true",
                             help="Set the field to null.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_REQUIREMENT_UPDATE_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"field": parsed.field}
    if parsed.null:
        payload["value"] = None
    else:
        payload["value"] = parsed.value
    return dispatch_and_emit(
        function_id="qa.requirement.update",
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=int(parsed.requirement_id),
        ),
        payload=payload,
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


QA_REQUIREMENT_WAIVE_USAGE = (
    "yoke qa requirement waive --requirement-id N --rationale TEXT "
    "[--source operator|agent] [--force] [--session-id S] [--json]"
)


def _write_waive_result(
    response: FunctionCallResponse,
    stdout: TextIO,
    _stderr: TextIO,
) -> None:
    result = response.result
    if "requirement_id" in result and "source" in result:
        print(
            f"Waived requirement {result['requirement_id']} "
            f"(source={result['source']})",
            file=stdout,
        )
    else:
        print(json.dumps(result, sort_keys=True), file=stdout)


def qa_requirement_waive(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa requirement waive",
        description=QA_REQUIREMENT_WAIVE_USAGE,
    )
    parser.add_argument("--requirement-id", dest="requirement_id",
                        type=int, required=True,
                        help="Target qa_requirements.id.")
    parser.add_argument("--rationale", required=True,
                        help="Reason this requirement is waived.")
    parser.add_argument("--source", choices=("operator", "agent"),
                        default="agent",
                        help="Waiver authority source.")
    parser.add_argument("--force", action="store_true",
                        help="Required to waive a blocking requirement.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_REQUIREMENT_WAIVE_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="qa.requirement.waive",
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=int(parsed.requirement_id),
        ),
        payload={
            "rationale": parsed.rationale,
            "source": parsed.source,
            "force": bool(parsed.force),
        },
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_write_waive_result,
    )


QA_RUN_RECORD_VERDICT_USAGE = (
    "yoke qa run record-verdict --requirement-id N "
    "--executor-type TYPE --verdict VERDICT "
    "[--raw-result TEXT] [--duration-ms N] [--session-id S] [--json]"
)


def qa_run_record_verdict(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa run record-verdict",
        description=QA_RUN_RECORD_VERDICT_USAGE,
    )
    parser.add_argument("--requirement-id", dest="requirement_id",
                        type=int, required=True,
                        help="Target qa_requirements.id.")
    parser.add_argument("--executor-type", dest="executor_type", required=True,
                        help="Executor that ran the QA check.")
    parser.add_argument("--verdict", required=True,
                        help="One of the registered QA verdicts.")
    parser.add_argument("--raw-result", dest="raw_result", default=None,
                        help="Optional raw output snippet.")
    parser.add_argument("--duration-ms", dest="duration_ms",
                        type=int, default=None,
                        help="Optional duration in milliseconds.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_RUN_RECORD_VERDICT_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {
        "executor_type": parsed.executor_type,
        "verdict": parsed.verdict,
    }
    if parsed.raw_result is not None:
        payload["raw_result"] = parsed.raw_result
    if parsed.duration_ms is not None:
        payload["duration_ms"] = int(parsed.duration_ms)
    return dispatch_and_emit(
        function_id="qa.run.record_verdict",
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=int(parsed.requirement_id),
        ),
        payload=payload,
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


QA_REQUIREMENT_AUTO_CREATE_FOR_ITEM_USAGE = (
    "yoke qa requirement auto-create-for-item --item PREFIX-N "
    "[--session-id S] [--json]"
)

USAGE_BY_FUNCTION_ID = {
    "qa.requirement.update": QA_REQUIREMENT_UPDATE_USAGE,
    "qa.requirement.auto_create_for_item":
        QA_REQUIREMENT_AUTO_CREATE_FOR_ITEM_USAGE,
    "qa.requirement.waive": QA_REQUIREMENT_WAIVE_USAGE,
    "qa.run.record_verdict": QA_RUN_RECORD_VERDICT_USAGE,
}


_AUTO_CREATE_FOR_ITEM_HELP_DEEP = """\
Idempotently seed one ``ac_verification`` requirement for a non-browser
issue item. Reads the item's structured fields, decides whether a
default unit-test QA requirement is appropriate, and inserts one row in
``qa_requirements`` when so. The call is a no-op for browser-testable
items, items with an existing unwaived requirement, and non-issue types.

Worked example:

  yoke qa requirement auto-create-for-item --item YOK-N
  yoke qa requirement auto-create-for-item --item 1833 --json

Outcomes (rendered in ``result.outcome``):

  - created               — one new ac_verification row was inserted.
  - existing              — an unwaived requirement already covered this item.
  - browser_testable_noop — the item is browser-testable; nothing inserted.
  - not_applicable        — non-issue type or browser-section signals no need.

Canonical vocabulary:

  --item PREFIX-N    Target item id. Accepts PREFIX-N, PREFIX-0N, or project-local number N.
  --session-id S  Override the resolved session id; defaults to env chain.
  --json          Emit the typed FunctionCallResponse envelope on stdout.

Flag matrix:

  flag           required  default                value shape
  --item         yes       —                      PREFIX-N or project-local number
  --session-id   no        $YOKE_SESSION_ID     opaque session id
  --json         no        false                  flag (no value)

Exit codes: 0 on success, 1 on dispatch failure (e.g. missing item), 2
on usage error.
"""


def qa_requirement_auto_create_for_item(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa requirement auto-create-for-item",
        description=(
            f"{QA_REQUIREMENT_AUTO_CREATE_FOR_ITEM_USAGE}\n\n"
            f"{_AUTO_CREATE_FOR_ITEM_HELP_DEEP}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--item", required=True,
                        help="Target item id (PREFIX-N or project-local number).")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, QA_REQUIREMENT_AUTO_CREATE_FOR_ITEM_USAGE,
    )
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="qa.requirement.auto_create_for_item",
        target=item_target("item", parsed.item, parsed.project),
        payload={},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )
