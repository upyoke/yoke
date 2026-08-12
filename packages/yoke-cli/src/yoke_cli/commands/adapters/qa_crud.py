"""``yoke qa requirement add / add-batch`` flag adapters.

Item-attached QA requirement creation over the dispatcher
(``qa.requirement.add`` / ``qa.requirement.add_batch``). Both are
item-claim-gated writes: the calling session must hold the active work
claim on the target item. Epic-task-attached and deployment-run-attached
creation stay on the operator-debug domain CLI
(``python3 -m yoke_core.domain.qa requirement-add --epic-id ...
--workflow-transition STAGE``). A deployment-run attachment may omit the
transition because its delivery run owns the context.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    usage_error,
)


QA_REQUIREMENT_ADD_USAGE = (
    "yoke qa requirement add --item PREFIX-N "
    "(--qa-kind KIND | --method-id METHOD) "
    "--qa-phase PHASE [--target-env E] [--blocking-mode M] "
    "[--requirement-source S] [--success-policy JSON-OR-TEXT] "
    "[--capability-requirements C] [--suite-id ID] "
    "--workflow-transition STAGE [--session-id S] [--json]"
)

_REQUIREMENT_ADD_HELP_DEEP = """\
Insert one item-attached qa_requirements row. Claim-gated: the calling
session must hold the active work claim on the item.

Worked examples:

  yoke qa requirement add --item YOK-N \\
    --qa-kind ac_verification --qa-phase verification \\
    --blocking-mode blocking --requirement-source ac_derived \\
    --workflow-transition reviewed-implementation

  yoke qa requirement add --item YOK-N \\
    --method-id browser-inspection --qa-phase verification \\
    --instructions "Open the login route and capture its ready state." \\
    --expected-outcome "The login form is aligned and usable." \\
    --method-config '{"steps":[{"action":"navigate","route":"/login"},
      {"action":"screenshot","capture":true,"name":"login"}]}' \\
    --workflow-transition reviewed-implementation

Flag matrix:

  flag                        required  default    value shape
  --item                      yes       —          PREFIX-N or number
  --qa-kind                   one-of    —          ad hoc legacy/plumbing discriminator
  --method-id                 one-of    —          registered QA method id
  --qa-phase                  yes       —          verification | post_deploy | manual_acceptance
  --target-env                no        —          env name
  --blocking-mode             no        blocking   blocking | non_blocking
  --requirement-source        no        explicit   explicit | seeded_default | ac_derived | flow_derived
  --instructions              method    —          what the case executes
  --expected-outcome          method    —          observable passing outcome
  --method-config             method    —          method-specific JSON object
  --workflow-transition      yes       —          pinned workflow stage id
  --success-policy            no        —          aggregate/ad hoc policy
  --capability-requirements   no        —          capability slug (e.g. browser-qa)
  --suite-id                  no        —          suite id string
  --session-id                no        ambient    opaque session id (operator-debug)
  --json                      no        false      flag (typed envelope on stdout)

Epic-task / deployment-run attachment: operator-debug domain CLI only.
Exit codes: 0 success, 1 dispatch failure (e.g. claim_required), 2 usage.
"""


def qa_requirement_add(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa requirement add",
        description=(f"{QA_REQUIREMENT_ADD_USAGE}\n\n{_REQUIREMENT_ADD_HELP_DEEP}"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--item", required=True, help="Target item (PREFIX-N or number)."
    )
    case_kind = parser.add_mutually_exclusive_group(required=True)
    case_kind.add_argument(
        "--qa-kind",
        dest="qa_kind",
        help="Requirement kind (verification plumbing).",
    )
    case_kind.add_argument(
        "--method-id",
        dest="method_id",
        help="Registered method for an executable case.",
    )
    parser.add_argument(
        "--qa-phase",
        dest="qa_phase",
        required=True,
        help="Lifecycle phase the requirement gates.",
    )
    parser.add_argument(
        "--target-env",
        dest="target_env",
        default=None,
        help="Optional target environment.",
    )
    parser.add_argument(
        "--blocking-mode",
        dest="blocking_mode",
        default="blocking",
        help="blocking (default) or non_blocking.",
    )
    parser.add_argument(
        "--requirement-source",
        dest="requirement_source",
        default="explicit",
        help="Provenance of the requirement.",
    )
    parser.add_argument(
        "--success-policy",
        dest="success_policy",
        default=None,
        help="Policy text; browser kinds require steps JSON.",
    )
    parser.add_argument(
        "--capability-requirements",
        dest="capability_requirements",
        default=None,
        help="Capability slug the runner needs.",
    )
    parser.add_argument(
        "--suite-id", dest="suite_id", default=None, help="Optional suite id."
    )
    parser.add_argument(
        "--instructions", default=None, help="Method case instructions."
    )
    parser.add_argument(
        "--expected-outcome",
        dest="expected_outcome",
        default=None,
        help="Method case passing outcome.",
    )
    parser.add_argument(
        "--method-config",
        dest="method_config",
        default=None,
        help="Method-specific JSON object.",
    )
    parser.add_argument(
        "--workflow-transition",
        dest="workflow_transition_id",
        required=True,
        help="Pinned workflow stage this requirement governs.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_REQUIREMENT_ADD_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {
        "qa_phase": parsed.qa_phase,
        "blocking_mode": parsed.blocking_mode,
        "requirement_source": parsed.requirement_source,
    }
    if parsed.qa_kind is not None:
        payload["qa_kind"] = parsed.qa_kind
    if parsed.method_id is not None:
        payload["method_id"] = parsed.method_id
    for key in (
        "target_env",
        "success_policy",
        "capability_requirements",
        "suite_id",
        "instructions",
        "expected_outcome",
        "workflow_transition_id",
    ):
        value = getattr(parsed, key)
        if value is not None:
            payload[key] = value
    if parsed.method_config is not None:
        try:
            method_config = json.loads(parsed.method_config)
        except json.JSONDecodeError as exc:
            return usage_error(f"--method-config must be valid JSON: {exc}")
        if not isinstance(method_config, dict):
            return usage_error("--method-config must be a JSON object")
        payload["method_config"] = method_config
    return dispatch_and_emit(
        function_id="qa.requirement.add",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
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
    "QA_REQUIREMENT_ADD_USAGE",
    "QA_REQUIREMENT_ADD_BATCH_USAGE",
    "qa_requirement_add",
    "qa_requirement_add_batch",
]
