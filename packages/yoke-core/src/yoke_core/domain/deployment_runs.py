"""Top-level deployment_runs shim — re-exports public names + CLI entrypoint.

Implementation lives in responsibility-named siblings. Each public name is
imported DIRECTLY from its canonical owner — no two-hop indirection through
another shim (the matching shim integrity rule for this lane).
"""

from __future__ import annotations

import sys

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

# Run CRUD — read paths
from yoke_core.domain.deployment_runs_crud_query import (  # noqa: F401
    cmd_find_by_item,
    cmd_get,
    cmd_items,
    cmd_list,
)

# Run CRUD — mutate paths
from yoke_core.domain.deployment_runs_crud_mutate import (  # noqa: F401
    cmd_add_item,
    cmd_create_run,
    cmd_next_id,
    cmd_remove_item,
    cmd_update,
)

# Lineage
from yoke_core.domain.deployment_runs_lineage import (  # noqa: F401
    cmd_lineage,
    cmd_lineage_create,
    cmd_lineage_final_status,
)

# QA checks on the run
from yoke_core.domain.deployment_runs_qa import (  # noqa: F401
    cmd_qa_add,
    cmd_qa_list,
    cmd_qa_update,
)

# Composition / batch validation
from yoke_core.domain.deployment_runs_validation import (  # noqa: F401
    cmd_check_batch_compatibility,
    cmd_validate_composition,
)

# Preview-environment lifecycle (incl. private ``_emit_event`` helper)
from yoke_core.domain.deployment_runs_preview import (  # noqa: F401
    _emit_event,
    cmd_can_cleanup_preview,
    cmd_check_preview_occupancy,
    cmd_claim_preview,
    cmd_preview_check,
    cmd_preview_claim,
    cmd_preview_release,
    cmd_resolve_target_env,
)

# CLI dispatcher
from yoke_core.domain.deployment_runs_cli import main  # noqa: F401


__all__ = [
    "RUN_FIELDS",
    "UPDATABLE_FIELDS",
    "VALID_ENV_TYPES",
    "VALID_QA_STATUSES",
    "VALID_STATUSES",
    "cmd_add_item",
    "cmd_can_cleanup_preview",
    "cmd_check_batch_compatibility",
    "cmd_check_preview_occupancy",
    "cmd_claim_preview",
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
    "cmd_preview_check",
    "cmd_preview_claim",
    "cmd_preview_release",
    "cmd_qa_add",
    "cmd_qa_list",
    "cmd_qa_update",
    "cmd_remove_item",
    "cmd_resolve_target_env",
    "cmd_update",
    "cmd_validate_composition",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
