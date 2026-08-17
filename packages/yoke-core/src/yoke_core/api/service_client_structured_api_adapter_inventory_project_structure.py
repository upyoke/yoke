"""Project Structure adapter-inventory slice.

The patch surface plus the read family — deploy defaults, the
architecture health computer, and the scan-derived draft proposal.
Spliced into the aggregate inventory so the main roster stays under
the authored-file cap.
"""

from __future__ import annotations

from typing import List

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry as _read_entry,
)


PROJECT_STRUCTURE_ADAPTERS: List[AdapterEntry] = [
    AdapterEntry(
        function_id="project_structure.patch.apply",
        cli_invocation=(
            "python3 -m yoke_core.cli.db_router project-structure patch-apply"
        ),
    ),
    _read_entry(
        function_id="project_structure.deploy_defaults.get",
        cli_invocation="yoke project-structure deploy-defaults get --project NAME",
    ),
    _read_entry(
        function_id="project_structure.architecture_health.get",
        cli_invocation=(
            "yoke project-structure architecture-health get --project NAME"
        ),
    ),
    _read_entry(
        function_id="project_structure.architecture_draft.get",
        cli_invocation=(
            "yoke project-structure architecture-draft get --project NAME"
        ),
    ),
]

__all__ = ["PROJECT_STRUCTURE_ADAPTERS"]
