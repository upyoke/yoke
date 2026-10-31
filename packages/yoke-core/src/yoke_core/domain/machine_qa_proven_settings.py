"""CAS writes of proven machine facts preserve existing verification."""

import json
from typing import Any, Mapping

from yoke_contracts.machine_config.test_machine import validate_test_machine_settings
from yoke_core.domain import db_backend
from yoke_core.domain.machine_qa_capability_rows import TestMachineCapabilityRow


def replace_proven_settings(
    conn: Any, row: TestMachineCapabilityRow, updates: Mapping[str, str]
) -> bool:
    """Merge validated facts only when the settings token still matches."""
    document = validate_test_machine_settings({**row.settings, **updates})
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    updated = conn.execute(
        f"UPDATE project_capabilities SET settings={marker} "
        f"WHERE project_id={marker} AND type={marker} AND "
        f"COALESCE(settings,'{{}}')={marker}",
        (
            json.dumps(document, separators=(",", ":"), sort_keys=True),
            row.project_id,
            row.capability_type,
            row.settings_token,
        ),
    )
    return updated.rowcount == 1
