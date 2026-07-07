"""Backlog mutation orchestration command surface — thin re-export shim.

Each public ``cmd_*`` symbol is owned by a responsibility-named sibling
module under ``runtime/api/service_client_backlog_*``.  Importers that say
``from yoke_core.api.service_client_backlog import cmd_xxx`` keep working
because each name is re-exported here directly from its canonical owner
(no two-hop indirection).
"""

from __future__ import annotations

from yoke_core.api.service_client_backlog_batch_update import (
    cmd_execute_batch_update,
    cmd_execute_batch_update_cli,
)
from yoke_core.api.service_client_backlog_close import cmd_execute_close
from yoke_core.api.service_client_backlog_create import (
    cmd_execute_create,
    cmd_execute_create_cli,
)
from yoke_core.api.service_client_backlog_github import cmd_backlog_github
from yoke_core.api.service_client_backlog_query import (
    cmd_backlog_dedup_search,
    cmd_backlog_list_cli,
)
from yoke_core.api.service_client_backlog_router import cmd_backlog_cli
from yoke_core.api.service_client_backlog_structured_write import (
    cmd_execute_structured_write,
)
from yoke_core.api.service_client_backlog_update import (
    cmd_execute_update,
    cmd_execute_update_cli,
)


__all__ = [
    "cmd_execute_create",
    "cmd_execute_create_cli",
    "cmd_execute_update",
    "cmd_execute_update_cli",
    "cmd_execute_structured_write",
    "cmd_execute_close",
    "cmd_execute_batch_update",
    "cmd_execute_batch_update_cli",
    "cmd_backlog_dedup_search",
    "cmd_backlog_list_cli",
    "cmd_backlog_github",
    "cmd_backlog_cli",
]
