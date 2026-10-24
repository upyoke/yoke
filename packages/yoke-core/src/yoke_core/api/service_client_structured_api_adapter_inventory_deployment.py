"""Adapter inventory rows for the ``yoke deployment-flows`` and
``yoke deployment-runs`` command families.

Each row records the canonical ``yoke <subcommand>`` usage, which must match
the CLI's own usage line. read_shape mirrors each handler's declared
side-effects (reads have none).
"""

from __future__ import annotations

from typing import List

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry as _read_entry,
)

DEPLOYMENT_ADAPTERS: List[AdapterEntry] = [
    _read_entry(
        function_id="deployment_runs.execution.containment_basis",
        cli_invocation=(
            "yoke deployment-runs execution containment-basis RUN-ID [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="deployment_flows.list",
        cli_invocation=(
            "yoke deployment-flows list [--project P] [--include-disabled] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="deployment_flows.get",
        cli_invocation=(
            "yoke deployment-flows get FLOW-ID [FIELD] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="deployment_flows.stages",
        cli_invocation=(
            "yoke deployment-flows stages FLOW-ID [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="deployment_flows.set_status",
        cli_invocation=(
            "yoke deployment-flows set-status FLOW-ID active|disabled [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="deployment_flows.create",
        cli_invocation=(
            "yoke deployment-flows create FLOW-ID --project P --name NAME (--stages-json JSON | --stages-file PATH | --stdin) [--description TEXT] [--on-failure halt|continue] [--target-tier persistent|ephemeral] [--environment ENV] [--done-description TEXT] [--takes-delivery-custody true|false] [--status active|disabled] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="deployment_flows.update",
        cli_invocation=(
            "yoke deployment-flows update FLOW-ID [--name NAME] [--description TEXT] [--stages-json JSON | --stages-file PATH | --stdin] [--on-failure halt|continue] [--target-tier persistent|ephemeral|none] [--environment ENV] [--done-description TEXT] [--takes-delivery-custody true|false] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="deployment_flows.reorder",
        cli_invocation=(
            "yoke deployment-flows reorder FLOW-ID --order NAME,NAME [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="deployment_flows.validate",
        cli_invocation=(
            "yoke deployment-flows validate --project P (--stages-json JSON | --stages-file PATH | --stdin) [--target-tier persistent|ephemeral] [--environment ENV] [--status active|disabled] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="deployment_flows.version",
        cli_invocation=(
            "yoke deployment-flows version SOURCE-FLOW NEW-FLOW --name "
            "NAME [--status active|disabled] "
            "[--session-id S] [--json] [--description DESCRIPTION] "
            "[--stages-json TEXT] [--stages-file PATH] [--stdin] "
            "[--on-failure {halt,continue}] [--target-tier "
            "{persistent,ephemeral,none}] [--environment ENVIRONMENT] "
            "[--done-description DONE_DESCRIPTION] "
            "[--takes-delivery-custody {true,false}]"
        ),
    ),
    AdapterEntry(
        function_id="deployment_flows.update_stages",
        cli_invocation=(
            "yoke deployment-flows update-stages FLOW-ID (--stages-json JSON | --stages-file PATH | --stdin) [--description TEXT] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="deployment_flows.describe",
        cli_invocation=(
            "yoke deployment-flows describe FLOW-ID (--description TEXT | --description-file PATH) [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="deployment_runs.carried_work.repair",
        cli_invocation=(
            "yoke deployment-runs carried-work repair RUN-ID [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="deployment_runs.release_output.record",
        cli_invocation=(
            "yoke deployment-runs release-output record RUN-ID --project P [--commit REF] [--promotion-receipt-file PATH] [--reason R] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="deployment_runs.create",
        cli_invocation=(
            "yoke deployment-runs create PROJECT FLOW --idempotency-key KEY [--environment ENV] [--project-repo-path PATH --source-ref REF | --retry-of RUN-ID] [--artifact-json JSON | --artifact-file PATH] [--created-by WHO] [--allow-pin-regression] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="deployment_runs.project_snapshot",
        cli_invocation=(
            "yoke deployment-runs project-snapshot --snapshot-file PATH [--expected-destination-digest DIGEST] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="deployment_runs.approve",
        cli_invocation=(
            "yoke deployment-runs approve RUN-ID [--note TEXT] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="deployment_runs.stage_approval.evaluate",
        cli_invocation=(
            "yoke deployment-runs stage-approval evaluate RUN-ID --stage STAGE [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="deployment_runs.start_for_item",
        cli_invocation=(
            "yoke deployment-runs start-for-item ITEM [--project P] [--flow F] [--environment ENV] [--release-lineage LINEAGE] [--created-by WHO] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="deployment_runs.add_item",
        cli_invocation=(
            "yoke deployment-runs add-item RUN-ID PREFIX-N [--project P] [--intent progress|final] [--requirement-id N ...] [--plan-id N ...] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="deployment_runs.remove_item",
        cli_invocation=(
            "yoke deployment-runs remove-item RUN-ID PREFIX-N --reason TEXT [--project P] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="deployment_runs.validate_composition",
        cli_invocation=(
            "yoke deployment-runs validate-composition RUN-ID [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="deployment_runs.continue_for_item",
        cli_invocation="yoke deployment-runs continue-for-item PREFIX-N",
    ),
    _read_entry(
        function_id="deployment_runs.get",
        cli_invocation=(
            "yoke deployment-runs get RUN-ID [FIELD ...] [--full] [--include-member-closure] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="deployment_runs.list",
        cli_invocation=(
            "yoke deployment-runs list [--project P] [--status STATUS] [--relevance overview] [--limit N] [--cursor CURSOR] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="deployment_runs.find_by_item",
        cli_invocation=(
            "yoke deployment-runs find-by-item PREFIX-N [--project P] [--status STATUS] [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="deployment_runs.failure_trace",
        cli_invocation=(
            "yoke deployment-runs failure-trace RUN-ID [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="deployment_runs.stages",
        cli_invocation=(
            "yoke deployment-runs stages RUN-ID [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="deployment_runs.timings",
        cli_invocation=(
            "yoke deployment-runs timings RUN-ID [--full] [--session-id S] [--json]"
        ),
    ),
    _read_entry(
        function_id="deployment_runs.resolve_target",
        cli_invocation=(
            "yoke deployment-runs resolve-target PROJECT FLOW [--environment ENV] [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="deployment_runs.update",
        cli_invocation=(
            "yoke deployment-runs update RUN-ID FIELD VALUE [--force] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="deployment_runs.terminalize",
        cli_invocation=(
            "yoke deployment-runs terminalize RUN-ID --disposition {failed,cancelled} --reason TEXT [--session-id S] [--json]"
        ),
    ),
]

__all__ = ["DEPLOYMENT_ADAPTERS"]
