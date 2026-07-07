"""Delivery and deployment command handlers for the service_client CLI surface.

Thin re-export shim — the implementation is split across responsibility-named
siblings:

* :mod:`yoke_core.api.service_client_delivery_approval` — ``approve-check``,
  ``apply-approval``.
* :mod:`yoke_core.api.service_client_delivery_item_mutation` —
  ``create-item``, ``validate-update`` (legacy alias: ``update-item``).
* :mod:`yoke_core.api.service_client_delivery_dependency` —
  ``evaluate-gate``, ``plan-candidates``, plus the
  ``BlockerDetail`` → dict adapter.

Backlog mutation orchestration (``execute-create``, ``execute-update``,
``backlog-cli``, etc.) lives in :mod:`yoke_core.api.service_client_backlog`;
the names are re-exported below directly from that canonical owner for
the ``yoke_core.api.service_client_delivery`` public surface.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Sibling re-exports — approval, item mutation, dependency planning
# ---------------------------------------------------------------------------

from yoke_core.api.service_client_delivery_approval import (  # noqa: F401
    cmd_apply_approval,
    cmd_approve_check,
)
from yoke_core.api.service_client_delivery_dependency import (  # noqa: F401
    _blocker_detail_to_dict,
    cmd_evaluate_gate,
    cmd_plan_candidates,
)
from yoke_core.api.service_client_delivery_item_mutation import (  # noqa: F401
    cmd_create_item,
    cmd_update_item,
)

# ---------------------------------------------------------------------------
# Public backlog re-exports from the canonical backlog owner.
# Direct imports avoid two-hop indirection.
# ---------------------------------------------------------------------------

from yoke_core.api.service_client_backlog import (  # noqa: F401
    cmd_backlog_cli,
    cmd_backlog_dedup_search,
    cmd_backlog_github,
    cmd_backlog_list_cli,
    cmd_execute_batch_update,
    cmd_execute_batch_update_cli,
    cmd_execute_close,
    cmd_execute_create,
    cmd_execute_create_cli,
    cmd_execute_structured_write,
    cmd_execute_update,
    cmd_execute_update_cli,
)
