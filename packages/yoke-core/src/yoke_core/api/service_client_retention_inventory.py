"""Public universe retention command adapters."""

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
)

RETENTION_ADAPTERS = [
    AdapterEntry(
        "universe.retention.get", "yoke universe retention get", read_shape=True
    ),
    AdapterEntry("universe.prune.run", "yoke universe prune [--dry-run | --apply]"),
]
