"""deployment_runs_crud shim — re-exports CRUD names from canonical owners.

Each name is imported DIRECTLY from its canonical leaf to satisfy the
direct-only shim integrity rule for this lane (no two-hop indirection
through another shim).
"""

from __future__ import annotations

# Schema + row-shape primitives
from yoke_core.domain.deployment_runs_schema import (  # noqa: F401
    RUN_FIELDS,
    UPDATABLE_FIELDS,
    VALID_ENV_TYPES,
    VALID_QA_STATUSES,
    VALID_STATUSES,
    _RUN_SELECT,
    _pipe_row,
    _pipe_rows,
    cmd_init,
)

# Read-side CRUD
from yoke_core.domain.deployment_runs_crud_query import (  # noqa: F401
    cmd_find_by_item,
    cmd_get,
    cmd_items,
    cmd_list,
)

# Mutate-side CRUD
from yoke_core.domain.deployment_runs_crud_mutate import (  # noqa: F401
    cmd_add_item,
    cmd_create_run,
    cmd_next_id,
    cmd_remove_item,
    cmd_update,
)

# Lineage helpers
from yoke_core.domain.deployment_runs_lineage import (  # noqa: F401
    cmd_lineage,
    cmd_lineage_create,
    cmd_lineage_final_status,
)

# QA helpers
from yoke_core.domain.deployment_runs_qa import (  # noqa: F401
    cmd_qa_add,
    cmd_qa_list,
    cmd_qa_update,
)

# Event emission (preview-env path consumer)
from yoke_core.domain.deployment_runs_preview import _emit_event  # noqa: F401


__all__ = [
    "RUN_FIELDS",
    "UPDATABLE_FIELDS",
    "VALID_ENV_TYPES",
    "VALID_QA_STATUSES",
    "VALID_STATUSES",
    "cmd_add_item",
    "cmd_create_run",
    "cmd_find_by_item",
    "cmd_get",
    "cmd_init",
    "cmd_items",
    "cmd_lineage",
    "cmd_lineage_create",
    "cmd_lineage_final_status",
    "cmd_list",
    "cmd_next_id",
    "cmd_qa_add",
    "cmd_qa_list",
    "cmd_qa_update",
    "cmd_remove_item",
    "cmd_update",
]
