"""Adapter inventory rows for the operational ``yoke`` subcommand families.

These function ids are agent-facing ``yoke`` subcommands whose token forms
live in the dedicated ``yoke_cli.commands.registry_*`` sub-modules
(deployment, readiness, shepherd-dependency, ephemeral-env, strategy/event/
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
        function_id=FUNCTION_ID,
        cli_invocation=("yoke migration content-identity verify --entries-json JSON"),
    ),
    # Deployment flow/run reads + the run-row update writer.
    _read_entry(
        function_id="deployment_flows.list",
        cli_invocation="yoke deployment-flows list [--project P]",
    ),
    _read_entry(
        function_id="deployment_flows.get", cli_invocation="yoke deployment-flows get"
    ),
    _read_entry(
        function_id="deployment_flows.stages",
        cli_invocation="yoke deployment-flows stages",
    ),
    AdapterEntry(
        function_id="deployment_flows.set_status",
        cli_invocation="yoke deployment-flows set-status",
    ),
    AdapterEntry(
        function_id="deployment_flows.create",
        cli_invocation="yoke deployment-flows create FLOW-ID --project P",
    ),
    AdapterEntry(
        function_id="deployment_flows.update_stages",
        cli_invocation="yoke deployment-flows update-stages FLOW-ID --stages-file PATH",
    ),
    AdapterEntry(
        function_id="deployment_flows.describe",
        cli_invocation="yoke deployment-flows describe FLOW-ID --description TEXT",
    ),
    AdapterEntry(
        function_id="deployment_runs.create",
        cli_invocation="yoke deployment-runs create",
    ),
    AdapterEntry(
        function_id="deployment_runs.project_snapshot",
        cli_invocation=(
            "yoke deployment-runs project-snapshot --snapshot-file PATH"
        ),
    ),
    AdapterEntry(
        function_id="deployment_runs.approve",
        cli_invocation="yoke deployment-runs approve",
    ),
    AdapterEntry(
        function_id="deployment_runs.start_for_item",
        cli_invocation="yoke deployment-runs start-for-item PREFIX-N",
    ),
    _read_entry(
        function_id="deployment_runs.get", cli_invocation="yoke deployment-runs get"
    ),
    _read_entry(
        function_id="deployment_runs.list", cli_invocation="yoke deployment-runs list"
    ),
    _read_entry(
        function_id="deployment_runs.find_by_item",
        cli_invocation="yoke deployment-runs find-by-item PREFIX-N",
    ),
    _read_entry(
        function_id="deployment_runs.stages",
        cli_invocation="yoke deployment-runs stages RUN-ID",
    ),
    _read_entry(
        function_id="deployment_runs.resolve_target",
        cli_invocation="yoke deployment-runs resolve-target",
    ),
    AdapterEntry(
        function_id="deployment_runs.update",
        cli_invocation="yoke deployment-runs update",
    ),
    AdapterEntry(
        function_id="deployment_runs.terminalize",
        cli_invocation="yoke deployment-runs terminalize",
    ),
    # Ephemeral environment read/create/update.
    _read_entry(
        function_id="ephemeral_env.get",
        cli_invocation="yoke ephemeral-env get PROJECT BRANCH",
    ),
    AdapterEntry(
        function_id="ephemeral_env.create",
        cli_invocation="yoke ephemeral-env create PROJECT BRANCH",
    ),
    AdapterEntry(
        function_id="ephemeral_env.update", cli_invocation="yoke ephemeral-env update"
    ),
    # Arbitrary event emit.
    AdapterEntry(function_id="events.emit", cli_invocation="yoke events emit"),
    _read_entry(
        function_id="env.list.run",
        cli_invocation="yoke env list [--config PATH] [--json]",
        notes="Client-local sanitized connection inventory.",
    ),
    # Onboarding checklist run (machine-config seeded rows).
    AdapterEntry(
        function_id="onboard.checklist.run", cli_invocation="yoke onboard checklist"
    ),
    # Ouroboros entry writes.
    AdapterEntry(
        function_id="ouroboros.entry.insert",
        cli_invocation="yoke ouroboros entry insert",
    ),
    AdapterEntry(
        function_id="ouroboros.entry.mark_archived",
        cli_invocation="yoke ouroboros entry mark-archived",
    ),
    AdapterEntry(
        function_id="ouroboros.entry.mark_reviewed",
        cli_invocation="yoke ouroboros entry mark-reviewed",
    ),
    # Readiness reads + repair writers, and the path-claim required-gate read.
    _read_entry(
        function_id="readiness.check.run", cli_invocation="yoke readiness check"
    ),
    _read_entry(
        function_id="readiness.prd_validate.run",
        cli_invocation="yoke readiness prd-validate",
    ),
    AdapterEntry(
        function_id="readiness.repair_claim_coverage",
        cli_invocation="yoke readiness repair-claim-coverage",
    ),
    AdapterEntry(
        function_id="readiness.repair_stale_count",
        cli_invocation="yoke readiness repair-stale-count",
    ),
    _read_entry(
        function_id="claims.path.required_gate",
        cli_invocation="yoke claims path required-gate",
    ),
    # Shepherd dependency-edge writers.
    AdapterEntry(
        function_id="shepherd.dependency_add.run",
        cli_invocation="yoke shepherd dependency-add",
    ),
    AdapterEntry(
        function_id="shepherd.dependency_remove.run",
        cli_invocation="yoke shepherd dependency-remove",
    ),
    AdapterEntry(
        function_id="shepherd.dependency_update.run",
        cli_invocation="yoke shepherd dependency-update",
    ),
    # Strategy carry / checkpoint / master-plan surfaces (mixed read/write).
    _read_entry(
        function_id="strategy.carry.candidate_set",
        cli_invocation="yoke strategy carry candidate-set",
    ),
    AdapterEntry(
        function_id="strategy.carry.mark", cli_invocation="yoke strategy carry mark"
    ),
    AdapterEntry(
        function_id="strategy.carry.register_new",
        cli_invocation="yoke strategy carry register-new",
    ),
    _read_entry(
        function_id="strategy.carry.summary",
        cli_invocation="yoke strategy carry summary",
    ),
    _read_entry(
        function_id="strategy.checkpoint.latest",
        cli_invocation="yoke strategy checkpoint latest",
    ),
    AdapterEntry(
        function_id="strategy.checkpoint.record",
        cli_invocation="yoke strategy checkpoint record",
    ),
    _read_entry(
        function_id="strategy.master_plan_check.run",
        cli_invocation="yoke strategy master-plan-check",
    ),
    _read_entry(
        function_id="overview.activation.get",
        cli_invocation="yoke overview activation get",
    ),
    AdapterEntry(
        function_id="harness.machine_report.upsert",
        cli_invocation="yoke harness machine-report upsert --project-id N",
    ),
]


__all__ = ["OPS_ADAPTERS"]
