"""QA-family CLI recipes and function bindings."""

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
        function_id="qa.plan_execution.adopt",
        cli_invocation=(
            "yoke qa plan adopt [--item PREFIX-N] "
            "--execution-id ID --reason TEXT [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="qa.plan_execution.reconcile",
        cli_invocation=(
            "yoke qa plan reconcile --project P --execution-id ID --reason TEXT "
            "[--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="qa.plan_execution.abort",
        cli_invocation=(
            "yoke qa plan abort [--item PREFIX-N] "
            "--execution-id ID --reason TEXT [--project P]"
        ),
    ),
    AdapterEntry(
        function_id="qa.plan_review.submit",
        cli_invocation=(
            "yoke qa plan review-submit "
            "[--item PREFIX-N] [--project P] "
            "--execution-id ID --bundle-id ID --bundle-digest SHA256 "
            "--stdin [--session-id S]"
        ),
    ),
    AdapterEntry(
        function_id="qa.plan_review.begin",
        cli_invocation="yoke qa plan review-begin [--item PREFIX-N] [--project P] --execution-id ID [--session-id S] [--json]",
    ),
    _read_entry(
        function_id="qa.method.list",
        cli_invocation=("yoke qa method list [--project P] [--session-id S] [--json]"),
    ),
    _read_entry(
        function_id="qa.method.get",
        cli_invocation=(
            "yoke qa method get METHOD [--project P] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "qa.project_method.register",
        (
            "yoke qa project-method register --project P --slug SLUG "
            "--name NAME --description TEXT --runner worktree_run "
            "--verdict-path automatic --verdict-contract TEXT "
            "--evidence-contract TEXT [--required-capability KIND ...] "
            "[--session-id S] [--json] [--concurrency-mode "
            "{parallel,serial}] [--success-policy-params JSON]"
        ),
    ),
    _read_entry(
        function_id="qa.plan.list",
        cli_invocation=(
            "yoke qa plan list --project P [--limit N] [--offset N] "
            "[--include-retired] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="qa.plan.get",
        cli_invocation=(
            "yoke qa plan get (PLAN_ID_OR_SLUG | --plan-id PLAN_ID_OR_SLUG) --project P [--deployment-run-id RUN] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="qa.activity.list",
        cli_invocation=(
            "yoke qa activity list --project P [--deployment-run-id RUN] [--item PREFIX-N ...] [--limit N] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="qa.artifact.read",
        cli_invocation=(
            "yoke qa artifact read --requirement-id N --artifact-id N "
            "[--output PATH] [--region x,y,w,h] [--scale N] "
            "[--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="qa.artifact.get",
        cli_invocation=(
            "yoke qa artifact get (ARTIFACT_ID | --artifact-id ARTIFACT_ID) --requirement-id N [--full] [--session-id S] [--json] (metadata only; use `yoke qa artifact read` for evidence)"
        ),
    ),
    AdapterEntry(
        "qa.plan.create",
        (
            "yoke qa plan create SLUG --project P "
            "--environment ENV [--session-id S] [--json] "
            "[--name NAME] [--description TEXT]"
        ),
    ),
    AdapterEntry(
        "qa.plan.edit",
        (
            "yoke qa plan edit PLAN_SLUG [--project P] [--editor COMMAND] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "qa.plan_cases.replace",
        (
            "yoke qa plan-cases replace --project P --plan-id N (--stdin | "
            "--cases-file PATH) [--source-revision FULL_SHA] [--session-id S] "
            "[--json]"
        ),
    ),
    AdapterEntry(
        "qa.plan_cases.sync",
        (
            "yoke qa plan-cases sync --project P --plan-id N (--cases-file PATH | --stdin) [--session-id S] [--json]\n       yoke qa plan-cases sync --project P --plan-id N (--cases-file PATH | --stdin) --source-revision FULL_SHA [--session-id S] [--json]\nWithout --source-revision, the input must be the exporter's document. Write a manual case array with yoke qa plan-cases replace."
        ),
    ),
    AdapterEntry(
        "qa.registered_command.set",
        (
            "yoke qa registered-command set --project P --scope "
            "quick|full|e2e|smoke --command ARGV [--environment "
            "SITE/NAME|ENV_ID | --requires-base-url] [--session-id S] "
            "[--json]"
        ),
    ),
    AdapterEntry(
        "qa.no_tests.attest",
        (
            'yoke qa no-tests attest --project P --reason "why this '
            'project has no suite to bind" [--session-id S] [--json]'
        ),
    ),
    AdapterEntry(
        "qa.no_tests.clear",
        (
            'yoke qa no-tests clear --project P --reason "what changed" '
            "[--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "qa.project_default.set",
        (
            "yoke qa project-default set --project P --plan-id N --workflow "
            "W --transition T [--session-id S] [--json] [--qa-phase PHASE] "
            "[--acknowledge-unreachable-target]"
        ),
    ),
    AdapterEntry(
        "qa.project_default.unset",
        (
            "yoke qa project-default unset --project P --plan-id N "
            "--workflow W --transition T [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "qa.item_plan.attach",
        (
            "yoke qa item-plan attach --item PREFIX-N --project P "
            "--plan-id N --transition T [--qa-phase post_deploy] "
            "[--acknowledge-unreachable-target] [--session-id S] "
            "[--json]"
        ),
    ),
    AdapterEntry(
        "qa.item_plan.retract",
        "yoke qa item-plan retract --item PREFIX-N --project P --plan-id N "
        "--transition T (--reason TEXT | --content-file PATH | --stdin) "
        "[--source operator|agent] [--session-id S] [--json]",
    ),
    AdapterEntry(
        "qa.plan.retire",
        (
            "yoke qa plan retire PLAN [--project P] (--reason TEXT | --content-file PATH | --stdin) [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "qa.plan.materialize",
        (
            "yoke qa plan materialize (--item PREFIX-N (--transition T | --stage "
            "STAGE [--plan PLAN]) [--project P] | --deployment-run-id RUN --project "
            "P (--plan PLAN [--stage STAGE] | --stage STAGE)) [--replaces "
            "CASE_KEY=REQUIREMENT_ID ...] [--replaces-requirement REQUIREMENT_ID "
            "...] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "qa.plan.rematerialize",
        (
            "yoke qa plan rematerialize (--item PREFIX-N (--transition T | --stage "
            "STAGE [--plan PLAN]) | --deployment-run-id RUN --stage STAGE [--plan "
            "PLAN]) [--project P] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "qa.requirement.transfer",
        (
            "yoke qa requirement transfer --requirement-id N --to-item PREFIX-N --workflow-transition STAGE --rationale TEXT [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "qa.requirement.update",
        "yoke qa requirement update --requirement-id N --field FIELD "
        "(--value VALUE | --content-file PATH | --stdin | --null) "
        "[--session-id S] [--json]",
    ),
    AdapterEntry(
        "qa.requirement.rebind_target",
        "yoke qa requirement rebind-target --requirement-id N "
        "(--rationale TEXT | --content-file PATH | --stdin) "
        "[--session-id S] [--json]",
    ),
    AdapterEntry(
        "qa.requirement.supersede",
        (
            "yoke qa requirement supersede --requirement-id N --superseded-by-requirement-id N (--rationale TEXT | --content-file PATH | --stdin) [--declare-replacement | --reconcile] [--source operator|agent] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "qa.post_deploy.declare_none",
        "yoke qa post-deploy declare-none --item PREFIX-N "
        "(--reason TEXT | --content-file PATH | --stdin) [--project P] "
        "[--source operator|agent] [--session-id S] [--json]",
    ),
    AdapterEntry(
        "qa.post_deploy.record_no_obligation",
        "yoke qa post-deploy record-no-obligation --item PREFIX-N "
        "(--reason TEXT | --content-file PATH | --stdin) [--project P] "
        "[--session-id S] [--json]",
    ),
    AdapterEntry(
        "qa.requirement.waive",
        "yoke qa requirement waive --requirement-id N "
        "(--rationale TEXT | --content-file PATH | --stdin) "
        "[--source operator|agent] [--force] [--session-id S] [--json]",
    ),
    AdapterEntry(
        "qa.run.record_verdict",
        "yoke qa run record-verdict --requirement-id N "
        "--performed-by WHO --verdict VERDICT "
        "[--verdict-reason REASON] [--raw-result JSON] "
        "[--duration-ms N] [--session-id S] [--json]",
    ),
    # Public QA reads, item-attached creation, and gate-entry summary.
    _read_entry(
        function_id="qa.requirement.list",
        cli_invocation=(
            "yoke qa requirement list [--item PREFIX-N | --epic PREFIX-N | --deployment-run-id ID] [--project P] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="qa.requirement.get",
        cli_invocation=(
            "yoke qa requirement get (N | --requirement-id N) [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "qa.requirement.add",
        (
            "yoke qa requirement add (--item PREFIX-N | --deployment-run RUN-ID) (--qa-kind KIND | --method-id METHOD) --qa-phase PHASE [--target-env E] [--blocking-mode M] [--requirement-source S] [--success-policy all-pass|JSON] [--required-capability KIND ...] [--suite-id ID] [--instructions TEXT | --instructions-file PATH | --stdin] [--expected-outcome TEXT | --expected-outcome-file PATH] [--method-config JSON] [--host-baseline NAME | --starting-state as_is --starting-state-reason TEXT] [--workflow-transition STAGE] [--deployment-stage STAGE] [--deployment-member-item PREFIX-N] [--project P] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "qa.requirement.add_batch",
        (
            "yoke qa requirement add-batch --item PREFIX-N (--rows-file PATH | --stdin) [--project P] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="qa.run.list",
        cli_invocation=(
            "yoke qa run list [--requirement-id N] [--project P] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="qa.run.get",
        cli_invocation=(
            "yoke qa run get --run-id N [--project P] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="qa.gate_summary.run",
        cli_invocation=(
            "yoke qa gate-summary (--item PREFIX-N | --epic PREFIX-N --task-num K) --target {reviewed-implementation,implemented} [--project P] [--full] [--session-id S] [--json]"
        ),
    ),
    # Browser case DB legs consumed by the shared per-requirement runner.
    _read_entry(
        function_id="qa.browser_context.get",
        cli_invocation=(
            "yoke qa browser-context get (--item PREFIX-N | --deployment-run RUN-ID) --requirement-id N --project P [--expected-branch BRANCH] [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "qa.run.add",
        (
            "yoke qa run add --requirement-id N --performed-by TYPE [--qa-kind KIND] [--verdict V] [--verdict-reason REASON] [--execution-status captured|capture_failed] [--capture-degraded-reason TEXT] [--raw-result TEXT] [--head-sha SHA] [--duration-ms N] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "qa.run.complete",
        (
            "yoke qa run complete --requirement-id N --run-id N [--verdict V] [--verdict-reason REASON] [--execution-status captured|capture_failed] [--capture-degraded-reason TEXT] [--raw-result TEXT] [--duration-ms N] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "qa.artifact.add",
        (
            "yoke qa artifact add --requirement-id N --run-id N --artifact-type TYPE (--artifact-handle JSON | --content-base64 B64 --filename NAME | --content-file PATH) [--content-type CT] [--metadata JSON] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="qa.artifact.presign",
        cli_invocation=(
            "yoke qa artifact presign --requirement-id N --run-id N --filename NAME [--content-type CT] [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "qa.artifact.rehome",
        (
            "yoke qa artifact rehome --requirement-id N --artifact-id N [--artifact-id N ...] [--session-id S] [--json]"
        ),
    ),
]


__all__ = ["QA_ADAPTERS"]
