"""``yoke qa requirement add / add-batch`` flag adapters.

QA requirement creation over the dispatcher (``qa.requirement.add`` /
``qa.requirement.add_batch``). ``add`` attaches a case to an item with
``--item`` — a claim-gated write, so the calling session must hold the
item's active work claim — or straight to a deployment run with
``--deployment-run``, authorized by that run's project scope and
optionally naming the stage and member item the case is about. A
run-attached case omits the workflow transition, because its delivery run
owns that context rather than an item workflow. ``add-batch`` stays
item-attached; epic-task attachment stays on the operator-debug domain CLI
(``python3 -m yoke_core.domain.qa requirement-add --epic-id ...
--workflow-transition STAGE``).
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

from yoke_contracts.api.function_call import TargetRef
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.adapters.qa_requirement_add_help import (
    QA_REQUIREMENT_ADD_HELP_DEEP,
    QA_REQUIREMENT_ADD_USAGE,
)
from yoke_cli.commands.text_file import resolve_optional_text_source


def qa_requirement_add(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa requirement add",
        description=(f"{QA_REQUIREMENT_ADD_USAGE}\n\n{QA_REQUIREMENT_ADD_HELP_DEEP}"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subject = parser.add_mutually_exclusive_group(required=True)
    subject.add_argument("--item", help="Target item (PREFIX-N).")
    subject.add_argument(
        "--deployment-run",
        dest="deployment_run",
        help="Target deployment run (run-YYYYMMDD-NNN).",
    )
    parser.add_argument(
        "--deployment-stage",
        dest="deployment_stage",
        default=None,
        help="Run-attached: the pinned stage the case is about.",
    )
    parser.add_argument(
        "--deployment-member-item",
        dest="deployment_member_item",
        default=None,
        help="Run-attached: member item the case is about (needs a stage).",
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
        "--required-capability",
        dest="capability_requirements",
        action="append",
        default=None,
        help="Required capability kind; repeat for more than one.",
    )
    parser.add_argument(
        "--suite-id", dest="suite_id", default=None, help="Optional suite id."
    )
    parser.add_argument(
        "--instructions", default=None, help="Method case instructions."
    )
    parser.add_argument(
        "--instructions-file",
        dest="instructions_file",
        default=None,
        help="Read method case instructions from a path.",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read method case instructions from stdin.",
    )
    parser.add_argument(
        "--expected-outcome",
        dest="expected_outcome",
        default=None,
        help="Method case passing outcome.",
    )
    parser.add_argument(
        "--expected-outcome-file",
        dest="expected_outcome_file",
        default=None,
        help="Read the passing outcome from a path.",
    )
    parser.add_argument(
        "--method-config",
        dest="method_config",
        default=None,
        help="Method-specific JSON object.",
    )
    parser.add_argument("--host-baseline", dest="host_baseline", default=None)
    parser.add_argument(
        "--starting-state", dest="starting_state", choices=("as_is",), default=None
    )
    parser.add_argument(
        "--starting-state-reason", dest="starting_state_reason", default=None
    )
    parser.add_argument(
        "--workflow-transition",
        dest="workflow_transition_id",
        default=None,
        help="Item-attached: pinned workflow stage this case governs.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_REQUIREMENT_ADD_USAGE)
    if parsed is None:
        return 2
    if parsed.item and parsed.workflow_transition_id is None:
        return usage_error(
            "--workflow-transition is required with --item: an item case "
            "names the pinned workflow stage it governs"
        )
    try:
        instructions = resolve_optional_text_source(
            value=parsed.instructions,
            file_path=parsed.instructions_file,
            stdin=parsed.stdin,
            text_flag="--instructions",
            file_flag="--instructions-file",
        )
        expected_outcome = resolve_optional_text_source(
            value=parsed.expected_outcome,
            file_path=parsed.expected_outcome_file,
            stdin=False,
            text_flag="--expected-outcome",
            file_flag="--expected-outcome-file",
        )
    except ValueError as exc:
        return usage_error(str(exc))
    if parsed.deployment_run:
        if parsed.workflow_transition_id is not None:
            return usage_error(
                "--workflow-transition does not apply to --deployment-run: "
                "a run-attached case is governed by its deployment run"
            )
        if parsed.deployment_member_item and not parsed.deployment_stage:
            return usage_error(
                "--deployment-member-item names a check at a stage, so "
                "--deployment-stage is required with it"
            )
    elif parsed.deployment_stage or parsed.deployment_member_item:
        return usage_error(
            "--deployment-stage / --deployment-member-item describe a "
            "deployment run's own case; use --deployment-run, not --item"
        )
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
        "workflow_transition_id",
        "host_baseline",
        "starting_state",
        "starting_state_reason",
    ):
        value = getattr(parsed, key)
        if value is not None:
            payload[key] = value
    if instructions is not None:
        payload["instructions"] = instructions
    if expected_outcome is not None:
        payload["expected_outcome"] = expected_outcome
    if parsed.method_config is not None:
        try:
            method_config = json.loads(parsed.method_config)
        except json.JSONDecodeError as exc:
            return usage_error(f"--method-config must be valid JSON: {exc}")
        if not isinstance(method_config, dict):
            return usage_error("--method-config must be a JSON object")
        payload["method_config"] = method_config
    if parsed.deployment_run:
        if parsed.deployment_stage:
            payload["deployment_stage"] = parsed.deployment_stage
        if parsed.deployment_member_item:
            # Passed through as the operator typed it. The run knows its own
            # members, so it resolves a ref or an id there and names what it
            # actually carries when neither matches.
            payload["deployment_member_item"] = parsed.deployment_member_item
        target = TargetRef(
            kind="deployment_run",
            deployment_run_id=str(parsed.deployment_run).strip(),
            project_id=client_project_context(parsed.project),
        )
    else:
        target = item_target("item", parsed.item, parsed.project)
    return dispatch_and_emit(
        function_id="qa.requirement.add",
        target=target,
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "QA_REQUIREMENT_ADD_USAGE",
    "qa_requirement_add",
]
