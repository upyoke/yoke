"""Retained Yoke CLI adapters and their backing function ids.

The :class:`AdapterEntry` shape lives in
:mod:`service_client_structured_api_adapter_inventory_types`; each command
family's entries live in a sibling module, and this module keeps only the
legacy ``python3 -m`` rows, whose order a lint relies on. It concatenates the
lists into the one ``CLI_ADAPTERS`` surface consumers read.
"""

from __future__ import annotations

from typing import Dict, List
from yoke_core.api.service_client_retention_inventory import RETENTION_ADAPTERS
from yoke_core.api.service_client_structured_api_adapter_inventory_admission import (
    ADMISSION_ADAPTERS,
)

from yoke_core.api.service_client_structured_api_adapter_inventory_claims import (
    CLAIMS_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_installer import (
    INSTALLER_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_items import (
    ITEMS_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_github_actions import (
    GITHUB_ACTIONS_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_epic import (
    EPIC_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_direct_workflows import (
    DIRECT_WORKFLOW_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_qa import (
    QA_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_sessions import (
    SESSION_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_strategy import (
    STRATEGY_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_test_machine import (
    TEST_MACHINE_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_ops import (
    OPS_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_general import (
    GENERAL_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_deployment import (
    DEPLOYMENT_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_models import (
    MODELS_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_packets import (
    PACKET_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_organizations import (
    ORGANIZATION_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_project_structure import (
    PROJECT_STRUCTURE_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_projects import (
    PROJECT_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AGENT_PATH_VALUES,
    AdapterEntry,
    read_entry as _read_entry,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_workflows import (
    WORKFLOW_ADAPTERS,
)

CLI_ADAPTERS: List[AdapterEntry] = [
    *RETENTION_ADAPTERS,
    *EPIC_ADAPTERS,
    *DIRECT_WORKFLOW_ADAPTERS,
    AdapterEntry(
        "db_claim.amend",
        "python3 -m yoke_core.api.service_client db-claim-amend",
        notes="unified DB-claim amendment",
    ),
    *GENERAL_ADAPTERS,
    *SESSION_ADAPTERS,
    *ITEMS_ADAPTERS,
    # qa-family entries live in the _qa sibling module (350-cap split).
    *QA_ADAPTERS,
    *TEST_MACHINE_ADAPTERS,
    # Cross-family readers (db_router forms stay operator-debug).
    *PROJECT_ADAPTERS,
    *ORGANIZATION_ADAPTERS,
    *MODELS_ADAPTERS,
    *CLAIMS_ADAPTERS,
    *PROJECT_STRUCTURE_ADAPTERS,
    *STRATEGY_ADAPTERS,
    # Operational families wrapped by the registry_* sub-modules (deployment,
    # readiness, item-dependency, ephemeral-env, strategy-carry/checkpoint,
    # events/ouroboros) + onboard-checklist; parity-synced into the inventory.
    *OPS_ADAPTERS,
    *DEPLOYMENT_ADAPTERS,
    *ADMISSION_ADAPTERS,
    *GITHUB_ACTIONS_ADAPTERS,
    _read_entry(
        function_id="items.get.run",
        cli_invocation=("python3 -m yoke_core.cli.db_router items get YOK-N <field>"),
    ),
    _read_entry(
        function_id="events.query.run",
        cli_invocation="python3 -m yoke_core.cli.db_router events list",
    ),
    _read_entry(
        function_id="path_claims.conflicts.list",
        cli_invocation=(
            "python3 -m yoke_core.cli.db_router path-claims conflicts-list"
        ),
    ),
    _read_entry(
        function_id="doctor.run.run",
        cli_invocation="python3 -m yoke_core.engines.doctor",
    ),
    *WORKFLOW_ADAPTERS,
    *INSTALLER_ADAPTERS,
    *PACKET_ADAPTERS,
    AdapterEntry(
        "ouroboros.field_note.append",
        "python3 -m yoke_core.api.service_client field-note-log",
    ),
]


def adapter_index() -> Dict[str, AdapterEntry]:
    return {entry.function_id: entry for entry in CLI_ADAPTERS}


def _taught_adapters() -> List[AdapterEntry]:
    """Lazy import of the taught-adapter sibling."""
    try:
        from yoke_core.api.service_client_structured_api_adapter_inventory_taught import (
            TAUGHT_ADAPTERS,
        )
    except Exception:
        return []
    return list(TAUGHT_ADAPTERS)


def all_adapter_entries() -> List[AdapterEntry]:
    """Return registered + taught adapter entries (lint consumer)."""
    return list(CLI_ADAPTERS) + _taught_adapters()


__all__ = [
    "AGENT_PATH_VALUES",
    "AdapterEntry",
    "CLI_ADAPTERS",
    "adapter_index",
    "all_adapter_entries",
]
