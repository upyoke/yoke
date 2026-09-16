"""``yoke qa requirement add-batch`` flag adapter.

Several item-attached cases for ONE item, inserted in one transaction
(``qa.requirement.add_batch``). Sibling of
:mod:`yoke_cli.commands.adapters.qa_crud`, which owns single-case
authoring for both the item and deployment-run subjects; split so each
adapter stays under the authored-file line cap.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    usage_error,
)


QA_REQUIREMENT_ADD_BATCH_USAGE = (
    "yoke qa requirement add-batch --item PREFIX-N "
    "(--rows-file PATH | --stdin) [--session-id S] [--json]"
)

_REQUIREMENT_ADD_BATCH_HELP_DEEP = """\
Insert several qa_requirements rows for ONE item in one transaction.
Claim-gated like `yoke qa requirement add`. Input is a JSON array of
row objects with the same fields as the add flags (qa_kind or method_id,
qa_phase, method case contract, target_env, blocking_mode,
requirement_source, success_policy, capability_requirements, suite_id,
workflow_transition_id).
Rows may omit item_id; a row naming
a different item or any epic/deployment-run attachment is rejected.

Worked example:

  printf '%s' '[{"method_id":"browser-check","qa_phase":"verification",
  "instructions":"Check /login","expected_outcome":"Login renders",
  "method_config":{"steps":[{"action":"navigate","route":"/login"},
  {"action":"assert","selector":"form"}]},
  "workflow_transition_id":"reviewed-implementation"}]' |
  yoke qa requirement add-batch --item YOK-N --stdin

Flag matrix:

  flag          required        value shape
  --item        yes             PREFIX-N or project-local number
  --rows-file   yes (or stdin)  path to JSON array file
  --stdin       yes (or file)   read the JSON array from stdin
  --session-id  no              opaque session id (operator-debug)
  --json        no              flag (typed envelope on stdout)

The whole batch rolls back if any row fails validation; per-row
QARequirementCreated events emit after commit. Exit codes: 0 success,
1 dispatch failure, 2 usage error.
"""


def qa_requirement_add_batch(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa requirement add-batch",
        description=(
            f"{QA_REQUIREMENT_ADD_BATCH_USAGE}\n\n{_REQUIREMENT_ADD_BATCH_HELP_DEEP}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--item", required=True, help="Target item (PREFIX-N or number)."
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--rows-file",
        dest="rows_file",
        default=None,
        help="Path to a JSON array of row objects.",
    )
    source_group.add_argument(
        "--stdin", action="store_true", help="Read the JSON array from stdin."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_REQUIREMENT_ADD_BATCH_USAGE)
    if parsed is None:
        return 2
    if parsed.stdin:
        raw = sys.stdin.read()
    else:
        try:
            with open(parsed.rows_file, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            return usage_error(f"cannot read --rows-file: {exc}")
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as exc:
        return usage_error(f"rows input is not valid JSON: {exc}")
    if not isinstance(rows, list):
        return usage_error("rows input must be a JSON array of objects")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            return usage_error(f"row {index} must be a JSON object")
        transition_id = row.get("workflow_transition_id")
        if not isinstance(transition_id, str) or not transition_id.strip():
            return usage_error(f"row {index} requires workflow_transition_id")
    return dispatch_and_emit(
        function_id="qa.requirement.add_batch",
        target=item_target("item", parsed.item, parsed.project),
        payload={"rows": rows},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "QA_REQUIREMENT_ADD_BATCH_USAGE",
    "qa_requirement_add_batch",
]
