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

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry as _read_entry,
)

OPS_ADAPTERS: List[AdapterEntry] = [
    # Deployment flow/run reads + the run-row update writer.
    _read_entry(function_id="deployment_flows.get", cli_invocation="yoke deployment-flows get"),
    _read_entry(function_id="deployment_flows.stages", cli_invocation="yoke deployment-flows stages"),
    AdapterEntry(
        function_id="deployment_flows.set_status",
        cli_invocation="yoke deployment-flows set-status",
    ),
    AdapterEntry(function_id="deployment_runs.create", cli_invocation="yoke deployment-runs create"),
    _read_entry(function_id="deployment_runs.get", cli_invocation="yoke deployment-runs get"),
    _read_entry(function_id="deployment_runs.list", cli_invocation="yoke deployment-runs list"),
    _read_entry(function_id="deployment_runs.resolve_target_env", cli_invocation="yoke deployment-runs resolve-target-env"),
    AdapterEntry(function_id="deployment_runs.update", cli_invocation="yoke deployment-runs update"),
    # Ephemeral environment update.
    AdapterEntry(function_id="ephemeral_env.update", cli_invocation="yoke ephemeral-env update"),
    # Arbitrary event emit.
    AdapterEntry(function_id="events.emit", cli_invocation="yoke events emit"),
    # Onboarding checklist run (machine-config seeded rows).
    AdapterEntry(function_id="onboard.checklist.run", cli_invocation="yoke onboard checklist"),
    # Ouroboros entry writes + wrapup read.
    AdapterEntry(function_id="ouroboros.entry.insert", cli_invocation="yoke ouroboros entry insert"),
    AdapterEntry(function_id="ouroboros.entry.mark_archived", cli_invocation="yoke ouroboros entry mark-archived"),
    AdapterEntry(function_id="ouroboros.entry.mark_reviewed", cli_invocation="yoke ouroboros entry mark-reviewed"),
    _read_entry(function_id="ouroboros.wrapup.list", cli_invocation="yoke ouroboros wrapup list"),
    # Readiness reads + repair writers, and the path-claim required-gate read.
    _read_entry(function_id="readiness.check.run", cli_invocation="yoke readiness check"),
    _read_entry(function_id="readiness.prd_validate.run", cli_invocation="yoke readiness prd-validate"),
    AdapterEntry(function_id="readiness.repair_claim_coverage", cli_invocation="yoke readiness repair-claim-coverage"),
    AdapterEntry(function_id="readiness.repair_stale_count", cli_invocation="yoke readiness repair-stale-count"),
    _read_entry(function_id="claims.path.required_gate", cli_invocation="yoke claims path required-gate"),
    # Shepherd dependency-edge writers.
    AdapterEntry(function_id="shepherd.dependency_add.run", cli_invocation="yoke shepherd dependency-add"),
    AdapterEntry(function_id="shepherd.dependency_remove.run", cli_invocation="yoke shepherd dependency-remove"),
    AdapterEntry(function_id="shepherd.dependency_update.run", cli_invocation="yoke shepherd dependency-update"),
    # Strategy carry / checkpoint / master-plan surfaces (mixed read/write).
    _read_entry(function_id="strategy.carry.candidate_set", cli_invocation="yoke strategy carry candidate-set"),
    AdapterEntry(function_id="strategy.carry.mark", cli_invocation="yoke strategy carry mark"),
    AdapterEntry(function_id="strategy.carry.register_new", cli_invocation="yoke strategy carry register-new"),
    _read_entry(function_id="strategy.carry.summary", cli_invocation="yoke strategy carry summary"),
    _read_entry(function_id="strategy.checkpoint.latest", cli_invocation="yoke strategy checkpoint latest"),
    AdapterEntry(function_id="strategy.checkpoint.record", cli_invocation="yoke strategy checkpoint record"),
    _read_entry(function_id="strategy.master_plan_check.run", cli_invocation="yoke strategy master-plan-check"),
]


__all__ = ["OPS_ADAPTERS"]
