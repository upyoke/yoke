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
    AdapterEntry("qa.requirement.update", "yoke qa requirement update --requirement-id N --field FIELD --value VALUE"),
    AdapterEntry("qa.requirement.auto_create_for_item", "yoke qa requirement auto-create-for-item --item YOK-N"),
    AdapterEntry("qa.requirement.waive", "yoke qa requirement waive --requirement-id N --rationale TEXT"),
    AdapterEntry("qa.run.record_verdict", "python3 -m yoke_core.cli.db_router qa run-add"),
    # qa CRUD conversion slice: reads + item-attached creation
    # + gate-entry summary; db_router forms stay operator-debug fallbacks.
    _read_entry(function_id="qa.requirement.list", cli_invocation="python3 -m yoke_core.cli.db_router qa requirement-list"),
    _read_entry(function_id="qa.requirement.get", cli_invocation="python3 -m yoke_core.cli.db_router qa requirement-get"),
    AdapterEntry("qa.requirement.add", "python3 -m yoke_core.cli.db_router qa requirement-add"),
    AdapterEntry("qa.requirement.add_batch", "python3 -m yoke_core.cli.db_router qa requirement-add-batch"),
    _read_entry(function_id="qa.run.list", cli_invocation="python3 -m yoke_core.cli.db_router qa run-list"),
    _read_entry(function_id="qa.run.get", cli_invocation="yoke qa run get --run-id N"),
    _read_entry(function_id="qa.gate_summary.run", cli_invocation="python3 -m yoke_core.cli.db_router qa gate-summary"),
    # Browser-QA DB legs (consumed by the tool-shaped `yoke qa browser run`).
    _read_entry(function_id="qa.browser_context.get", cli_invocation="yoke qa browser-context get --item PREFIX-N --project P"),
    AdapterEntry("qa.run.add", "yoke qa run add --requirement-id N --executor-type TYPE"),
    AdapterEntry("qa.run.complete", "yoke qa run complete --requirement-id N --run-id N --verdict V"),
    AdapterEntry("qa.artifact.add", "yoke qa artifact add --requirement-id N --run-id N --artifact-type TYPE --artifact-handle JSON"),
    _read_entry(function_id="qa.artifact.presign", cli_invocation="yoke qa artifact presign --requirement-id N --run-id N --filename F"),
    _read_entry(function_id="qa.screenshot_evidence.pending_count", cli_invocation="yoke qa screenshot-evidence pending-count --item PREFIX-N"),
    AdapterEntry("qa.screenshot_evidence.satisfy", "yoke qa screenshot-evidence satisfy --item PREFIX-N"),
]


__all__ = ["QA_ADAPTERS"]
