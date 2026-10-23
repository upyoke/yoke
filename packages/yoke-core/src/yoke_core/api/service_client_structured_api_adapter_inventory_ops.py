"""Adapter inventory rows for the operational ``yoke`` subcommand families.

These function ids are agent-facing ``yoke`` subcommands whose token forms
live in the dedicated ``yoke_cli.commands.registry_*`` sub-modules
(readiness, item-dependency, ephemeral-env, strategy/event/
ouroboros) plus ``onboard checklist`` and the ``claims path required-gate``
read. The parity gate ``test_every_live_function_has_an_adapter_entry``
requires a CLI_ADAPTERS row for every ``adapter_status='live'`` handler;
these rows record the canonical ``yoke <subcommand>`` invocation. read_shape
mirrors each handler's declared side-effects (reads have none).
"""

from __future__ import annotations

from typing import List

from yoke_contracts.migration_content_identity import FUNCTION_ID
from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry as _read_entry,
)

OPS_ADAPTERS: List[AdapterEntry] = [
    _read_entry(
        function_id="advance.preflight.hard_blocks",
        cli_invocation="yoke advance preflight hard-blocks PREFIX-N [--gate-point POINT] [--json]",
    ),
    AdapterEntry(
        function_id="ouroboros.reflection.capture",
        cli_invocation=(
            "yoke ouroboros reflection capture (--text-file PATH | --stdin) [--default-agent ROLE] [--project P] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="operator.data_repair.run",
        cli_invocation=(
            "yoke operator data-repair --content-file FILE (--print-digest | --reviewed-sha256 SHA) [--dry-run] [--json]"
        ),
    ),
    _read_entry(
        function_id="events.performance.aggregate",
        cli_invocation=(
            "yoke events performance aggregate --since ISO --until ISO [--project-ids ID,ID] [--points N] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="events.performance.detail",
        cli_invocation=(
            "yoke events performance detail --since ISO --until ISO [--project-ids ID,ID] [--points N] [--family FAMILY] [--offset N] [--limit N] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="decision_requests.get",
        cli_invocation="yoke decision-requests get REQUEST_ID [--json]",
    ),
    _read_entry(
        function_id=FUNCTION_ID,
        cli_invocation=(
            "yoke migration content-identity verify --entries-json JSON "
            "[--full] [--session-id S] [--json]"
        ),
    ),
    # Deployment flow/run reads + the run-row update writer.
    AdapterEntry(
        function_id="merge_receipt.commits.attest",
        cli_invocation=(
            "yoke merge-receipt commits attest <PREFIX-N> --commit SHA [--commit SHA ...] --reason R [--project P] [--session-id S] [--json]"
        ),
    ),
    # Ephemeral environment read/create/update.
    _read_entry(
        function_id="ephemeral_env.get",
        cli_invocation=(
            "yoke ephemeral-env get PROJECT BRANCH [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="ephemeral_env.create",
        cli_invocation=(
            "yoke ephemeral-env create PROJECT BRANCH [--item PREFIX-N] [--workflow-run-id ID] [--github-ref REF] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="ephemeral_env.update",
        cli_invocation=(
            "yoke ephemeral-env update ENV-ID FIELD VALUE [--session-id S] [--json]"
        ),
    ),
    # Arbitrary event emit.
    AdapterEntry(
        function_id="events.emit",
        cli_invocation=(
            "yoke events emit --name NAME --kind KIND --type TYPE --source-type SOURCE [--severity LEVEL] [--outcome OUTCOME] [--project P] [--item PREFIX-N] [--task-num N] [--agent A] [--tool-name T] [--org-id ID] [--environment ENV] [--request-id ID] [--trace-id ID] [--parent-id ID] [--tool-use-id ID] [--turn-id ID] [--hook-event-name NAME] [--anomaly-flags FLAGS] [--duration-ms MS] [--exit-code CODE] [--context JSON] [--error-context JSON] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="env.list.run",
        cli_invocation="yoke env list [--config PATH] [--json]",
        notes="Client-local sanitized connection inventory.",
    ),
    # Scoped setup facts and saved choices.
    _read_entry(
        function_id="onboard.checklist.get",
        cli_invocation=(
            "yoke onboard checklist get [--project P] [--run-id RUN] [--config PATH] [--checkout PATH] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="onboard.checklist.run",
        cli_invocation=(
            "yoke onboard checklist [--run-id RUN] [--branch MODE] [--json] [--project-root PATH] [--project-id N] [--project P] [--config PATH] [--profile-file FILE] [--github-repo OWNER/REPO] [--row-status ROW=STATUS] [--evidence ROW=TEXT] [--blocker ROW=TEXT] [--note ROW=TEXT] [--view-path PATH | --no-view]"
        ),
    ),
    # Ouroboros entry writes.
    AdapterEntry(
        function_id="ouroboros.entry.insert",
        cli_invocation=(
            "yoke ouroboros entry insert --agent A --category C (--observation TEXT | --observation-file PATH | --stdin) [--context TEXT] [--timestamp TS] [--project P] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="ouroboros.entry.mark_archived",
        cli_invocation=(
            "yoke ouroboros entry mark-archived (--all-reviewed | ENTRY_ID) [--include-unattributed] [--project P] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="ouroboros.entry.mark_reviewed",
        cli_invocation=(
            "yoke ouroboros entry mark-reviewed (ENTRY_ID | --before YYYY-MM-DD | --field-notes-before YYYY-MM-DD) [--limit N] [--include-unattributed] [--project P] [--session-id S] [--json]"
        ),
    ),
    # Readiness reads + repair writers, and the path-claim required-gate read.
    _read_entry(
        function_id="readiness.check.run",
        cli_invocation=(
            "yoke readiness check PREFIX-N [--skip-readiness-check] [--full] [--project P] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="readiness.prd_validate.run",
        cli_invocation=(
            "yoke readiness prd-validate PREFIX-N [--strict] [--full] [--project P] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="readiness.repair_claim_coverage",
        cli_invocation=(
            "yoke readiness repair-claim-coverage --item PREFIX-N [--project P] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="readiness.repair_stale_count",
        cli_invocation=(
            "yoke readiness repair-stale-count --item PREFIX-N [--project P] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="claims.path.required_gate",
        cli_invocation=(
            "yoke claims path required-gate PREFIX-N [--project P] [--full] [--session-id S] [--json]"
        ),
    ),
    # Item-dependency writers.
    AdapterEntry(
        function_id="items.dependency.add",
        cli_invocation=(
            "yoke items dependency add <dependent> <blocking> <source> [--gate-point activation|integration|closure|coordination_only] [--satisfaction status:<stage-id>|fact:merged|fact:deployed:<environment-name>] (--rationale TEXT | --rationale-file PATH) [--evidence JSON | --evidence-file PATH] [--project P] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="items.dependency.remove",
        cli_invocation=(
            "yoke items dependency remove <dependent> <blocking> [--project P] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="items.dependency.update",
        cli_invocation=(
            "yoke items dependency update <dependent> <blocking> [--match-gate-point POINT] [--gate-point POINT] [--satisfaction status:<stage-id>|fact:merged|fact:deployed:<environment-name>] [--rationale TEXT | --rationale-file PATH] [--source SOURCE] [--evidence JSON | --evidence-file PATH] [--project P] [--session-id S] [--json]"
        ),
    ),
    # Strategy carry / checkpoint / master-plan surfaces (mixed read/write).
    _read_entry(
        function_id="strategy.carry.candidate_set",
        cli_invocation=(
            "yoke strategy carry candidate-set --project P [--horizon-days N] [--carry-limit N] [--new-ids ID ...] [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="strategy.carry.mark",
        cli_invocation=(
            "yoke strategy carry mark --project P --state STATE --items ID ... [--reason TEXT] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="strategy.carry.register_new",
        cli_invocation=(
            "yoke strategy carry register-new --project P [--horizon-days N] [--carry-limit N] [--result-json] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="strategy.carry.summary",
        cli_invocation=(
            "yoke strategy carry summary --project P [--horizon-days N] [--carry-limit N] [--new-ids ID ...] [--display-limit N] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="strategy.checkpoint.latest",
        cli_invocation=(
            "yoke strategy checkpoint latest --project P [--kind strategize|drift_review] [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="strategy.checkpoint.record",
        cli_invocation=(
            "yoke strategy checkpoint record --project P [--kind strategize|drift_review] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="strategy.master_plan_check.run",
        cli_invocation=(
            "yoke strategy master-plan-check [--plan-path PATH] [--exit-nonzero-on-drift] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="overview.activation.get",
        cli_invocation=(
            "yoke overview activation get [--machine-connected] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="harness.machine_report.upsert",
        cli_invocation=(
            "yoke harness machine-report upsert --project-id N [--repo-root PATH] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="merge_review.candidate.evaluate",
        cli_invocation=(
            "yoke merge-review candidate evaluate ITEM --commit SHA [--branch NAME] [--target BRANCH] [--touched-file PATH ...] [--project P] [--session-id S] [--json]"
        ),
        notes=(
            "Reports whether one exact candidate head may land, and raises "
            "the review that would clear it. The merge boundary calls it "
            "itself; a reviewer runs it to queue the review early."
        ),
    ),
]


__all__ = ["OPS_ADAPTERS"]
