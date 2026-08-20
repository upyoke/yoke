"""QA-family adapter entries for the structured-API adapter inventory.

Sibling of :mod:`service_client_structured_api_adapter_inventory` —
split out so the main inventory module stays under the authored-file
line cap. Concatenated into ``CLI_ADAPTERS`` by the parent module.
"""

from __future__ import annotations

from typing import List

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry as _read_entry,
)


QA_ADAPTERS: List[AdapterEntry] = [
    AdapterEntry(
        function_id="qa.case_execution.begin",
        cli_invocation="yoke qa case run --requirement-id N",
    ),
    AdapterEntry(
        function_id="qa.plan_execution.begin",
        cli_invocation=(
            "yoke qa plan run --deployment-run-id RUN --plan PLAN --project P"
        ),
    ),
    AdapterEntry(
        function_id="qa.plan_execution.abort",
        cli_invocation=(
            "yoke qa plan abort (--item PREFIX-N | --deployment-run-id RUN) "
            "--execution-id ID --reason TEXT [--project P]"
        ),
    ),
    AdapterEntry(
        function_id="qa.plan_review.submit",
        cli_invocation=(
            "yoke qa plan review-submit "
            "(--item-id N | --deployment-run-id RUN) "
            "--execution-id ID --bundle-id ID --bundle-digest SHA256 "
            "--stdin [--session-id S]"
        ),
    ),
    _read_entry(
        function_id="qa.method.list", cli_invocation="yoke qa method list --project P"
    ),
    _read_entry(
        function_id="qa.method.get",
        cli_invocation="yoke qa method get METHOD --project P",
    ),
    AdapterEntry(
        "qa.project_method.register",
        "yoke qa project-method register --project P --slug SLUG --name NAME --description TEXT --runner worktree_run --verdict-path automatic --verdict-contract TEXT --evidence-contract TEXT",
    ),
    _read_entry(
        function_id="qa.plan.list", cli_invocation="yoke qa plan list --project P"
    ),
    _read_entry(
        function_id="qa.plan.get",
        cli_invocation=(
            "yoke qa plan get PLAN_ID --project P [--deployment-run-id RUN]"
        ),
    ),
    _read_entry(
        function_id="qa.activity.list",
        cli_invocation=("yoke qa activity list --project P [--deployment-run-id RUN]"),
    ),
    _read_entry(
        function_id="qa.artifact.read",
        cli_invocation="yoke qa artifact read --requirement-id N --artifact-id N",
    ),
    AdapterEntry("qa.plan.create", "yoke qa plan create SLUG --project P"),
    AdapterEntry("qa.plan.edit", "yoke qa plan edit PLAN_SLUG --project P"),
    AdapterEntry(
        "qa.plan_cases.replace",
        "yoke qa plan-cases replace --project P --plan-id N --stdin",
    ),
    AdapterEntry(
        "qa.project_default.set",
        "yoke qa project-default set --project P --plan-id N --workflow W --transition T",
    ),
    AdapterEntry(
        "qa.project_default.unset",
        "yoke qa project-default unset --project P --plan-id N --workflow W --transition T",
    ),
    AdapterEntry(
        "qa.item_plan.attach",
        "yoke qa item-plan attach --item YOK-N --project P --plan-id N --transition T",
    ),
    AdapterEntry(
        "qa.plan.materialize",
        "yoke qa plan materialize --deployment-run-id RUN --plan PLAN --project P",
    ),
    AdapterEntry(
        "qa.plan.rematerialize",
        "yoke qa plan rematerialize --item PREFIX-N --transition T",
    ),
    AdapterEntry(
        "qa.requirement.update",
        "yoke qa requirement update --requirement-id N --field FIELD "
        "(--value VALUE | --null) [--session-id S] [--json]",
    ),
    AdapterEntry(
        "qa.requirement.waive",
        "yoke qa requirement waive --requirement-id N --rationale TEXT "
        "[--source operator|agent] [--force] [--session-id S] [--json]",
    ),
    AdapterEntry(
        "qa.run.record_verdict",
        "yoke qa run record-verdict --requirement-id N "
        "--performed-by WHO --verdict VERDICT "
        "[--raw-result TEXT] [--duration-ms N] [--session-id S] [--json]",
    ),
    # Public QA reads, item-attached creation, and gate-entry summary.
    _read_entry(
        function_id="qa.requirement.list",
        cli_invocation=(
            "yoke qa requirement list [--item PREFIX-N | --epic-id N | "
            "--deployment-run-id ID] [--project P] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="qa.requirement.get",
        cli_invocation=(
            "yoke qa requirement get --requirement-id N [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "qa.requirement.add",
        "yoke qa requirement add --item PREFIX-N "
        "(--qa-kind KIND | --method-id METHOD) "
        "--qa-phase PHASE [--target-env E] [--blocking-mode M] "
        "[--requirement-source S] [--success-policy JSON-OR-TEXT] "
        "[--required-capability KIND ...] [--suite-id ID] "
        "--workflow-transition STAGE [--session-id S] [--json]",
    ),
    AdapterEntry(
        "qa.requirement.add_batch",
        "yoke qa requirement add-batch --item PREFIX-N "
        "(--rows-file PATH | --stdin) [--session-id S] [--json]",
    ),
    _read_entry(
        function_id="qa.run.list",
        cli_invocation=(
            "yoke qa run list [--requirement-id N] [--project P] "
            "[--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="qa.run.get",
        cli_invocation=(
            "yoke qa run get --run-id N [--project P] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="qa.gate_summary.run",
        cli_invocation=(
            "yoke qa gate-summary "
            "(--item PREFIX-N | --epic-id N --task-num K) "
            "--target {reviewed-implementation,implemented} "
            "[--session-id S] [--json]"
        ),
    ),
    # Browser case DB legs consumed by the shared per-requirement runner.
    _read_entry(
        function_id="qa.browser_context.get",
        cli_invocation="yoke qa browser-context get --item PREFIX-N --requirement-id N --project P",
    ),
    AdapterEntry("qa.run.add", "yoke qa run add --requirement-id N --performed-by WHO"),
    AdapterEntry(
        "qa.run.complete",
        "yoke qa run complete --requirement-id N --run-id N --verdict V",
    ),
    AdapterEntry(
        "qa.artifact.add",
        "yoke qa artifact add --requirement-id N --run-id N --artifact-type TYPE --artifact-handle JSON",
    ),
    _read_entry(
        function_id="qa.artifact.presign",
        cli_invocation="yoke qa artifact presign --requirement-id N --run-id N --filename F",
    ),
]


__all__ = ["QA_ADAPTERS"]
