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


QA_REQUIREMENT_ADD_USAGE = (
    "yoke qa requirement add (--item PREFIX-N | --deployment-run RUN-ID) "
    "(--qa-kind KIND | --method-id METHOD) "
    "--qa-phase PHASE [--target-env E] [--blocking-mode M] "
    "[--requirement-source S] [--success-policy JSON-OR-TEXT] "
    "[--required-capability KIND ...] [--suite-id ID] "
    "[--workflow-transition STAGE] [--deployment-stage STAGE] "
    "[--deployment-member-item PREFIX-N] [--session-id S] [--json]"
)

_REQUIREMENT_ADD_HELP_DEEP = """\
Insert one qa_requirements row against the subject you name.

  --item PREFIX-N         the case is that item's own verification.
                          Claim-gated: the calling session must hold the
                          item's active work claim, and the case names the
                          pinned workflow stage it governs.
  --deployment-run RUN-ID the case is that release's own check. Authorized
                          by the run's project scope; no workflow stage,
                          because the run owns the context. Optionally
                          scoped to one --deployment-stage, and within it
                          one --deployment-member-item the run carries.
                          A run that has already finished is refused: its
                          evidence is closed. The case must name a method
                          (--method-id), and it never enters a stage's
                          materialized admission — it is evidence recorded
                          against the run, executed and read back through
                          the same `yoke qa case run` / `qa activity list`
                          surfaces an item case uses.

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

  yoke qa requirement add --deployment-run run-YYYYMMDD-NNN \\
    --method-id browser-inspection --qa-phase post_deploy \\
    --deployment-stage stage-smoke \\
    --instructions "Open the released home route and capture it." \\
    --expected-outcome "The home page renders the new build." \\
    --method-config '{"steps":[{"action":"navigate","route":"/"},
      {"action":"screenshot","capture":true,"name":"home"}]}'

Flag matrix:

  flag                        required  default    value shape
  --item                      one-of    —          PREFIX-N or number
  --deployment-run            one-of    —          run-YYYYMMDD-NNN
  --deployment-stage          no        —          run-attached: pinned stage name
  --deployment-member-item    no        —          run-attached: member PREFIX-N (needs stage)
  --qa-kind                   one-of    —          ad hoc legacy/plumbing discriminator
  --method-id                 one-of    —          registered QA method id
  --qa-phase                  yes       —          verification | post_deploy | manual_acceptance
  --target-env                no        —          env name
  --blocking-mode             no        blocking   blocking | non_blocking
  --requirement-source        no        explicit   explicit | seeded_default | ac_derived | flow_derived
  --instructions              method    —          what the case executes
  --expected-outcome          method    —          observable passing outcome
  --method-config             method    —          method-specific JSON object
  --workflow-transition      item      —          pinned workflow stage id
  --success-policy            no        —          aggregate/ad hoc policy
  --required-capability       no        —          repeatable capability kind
  --suite-id                  no        —          suite id string
  --session-id                no        ambient    opaque session id (operator-debug)
  --json                      no        false      flag (typed envelope on stdout)

Epic-task attachment: operator-debug domain CLI only.
Exit codes: 0 success, 1 dispatch failure (e.g. claim_required, a closed
run, a stage the run does not declare), 2 usage.
"""


def qa_requirement_add(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa requirement add",
        description=(f"{QA_REQUIREMENT_ADD_USAGE}\n\n{_REQUIREMENT_ADD_HELP_DEEP}"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subject = parser.add_mutually_exclusive_group(required=True)
    subject.add_argument("--item", help="Target item (PREFIX-N or number).")
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
