"""Canonical delivery-item lifecycle for the software-delivery workflow family.

This module is the single source of truth for delivery item and epic task
status constants, canonical progression order, board display order, terminal
checks, display-label rendering, and validation rules.

The implementation is split across responsibility-named siblings:

- ``lifecycle_enums`` -- canonical ``ItemStatus`` / ``TaskStatus`` /
  ``IssueStatus`` / ``EpicStatus`` enums plus the workflow-family scope
  metadata constants.
- ``lifecycle_predicates`` -- terminal/exceptional frozensets and the
  ``is_valid_*_status`` / ``is_terminal*`` / ``is_exceptional`` /
  ``is_task_terminal_success`` predicates.
- ``lifecycle_progression`` -- ``ALL_*_STATUSES`` tuples,
  ``EPIC_PROGRESSION`` / ``ISSUE_PROGRESSION`` / ``BOARD_COLUMN_ORDER`` and
  the ``progression_index`` / ``is_forward_transition`` helpers.
- ``lifecycle_sql`` -- ``sql_*_list`` SQL ``IN``-clause helpers and
  ``display_label`` rendering.

This front door re-exports the full historical public surface so existing
``from yoke_core.domain.lifecycle import ...`` callers continue to work
unchanged.  Each name is pulled directly from its canonical owner sibling --
no two-hop indirection through other shims.
"""

from __future__ import annotations

# -- enums + workflow-family scope metadata ---------------------------------
from yoke_core.domain.lifecycle_enums import (  # noqa: F401
    EpicStatus,
    IssueStatus,
    ItemStatus,
    LIFECYCLE_FAMILY,
    LIFECYCLE_SCOPE,
    TaskStatus,
)

# -- terminal/exceptional frozensets + validation predicates ----------------
from yoke_core.domain.lifecycle_predicates import (  # noqa: F401
    EXCEPTIONAL,
    TASK_TERMINAL_SUCCESS,
    TERMINAL,
    TERMINAL_FAILURE,
    TERMINAL_SUCCESS,
    is_exceptional,
    is_task_terminal_success,
    is_terminal,
    is_terminal_failure,
    is_terminal_success,
    is_valid_epic_status,
    is_valid_issue_status,
    is_valid_item_status,
    is_valid_task_status,
)

# -- ordered status collections + progression helpers -----------------------
from yoke_core.domain.lifecycle_progression import (  # noqa: F401
    ALL_EPIC_STATUSES,
    ALL_ISSUE_STATUSES,
    ALL_ITEM_STATUSES,
    ALL_TASK_STATUSES,
    BOARD_COLUMN_ORDER,
    EPIC_PROGRESSION,
    ISSUE_PROGRESSION,
    PRE_IMPLEMENTATION_STATUSES,
    epic_progression_index,
    is_epic_forward_transition,
    is_forward_transition,
    progression_index,
)

# -- SQL fragment helpers + human-readable display label --------------------
from yoke_core.domain.lifecycle_sql import (  # noqa: F401
    display_label,
    sql_task_terminal_success_list,
    sql_terminal_failure_list,
    sql_terminal_list,
    sql_terminal_success_list,
)

__all__ = [
    # enums + workflow-family scope metadata
    "EpicStatus",
    "IssueStatus",
    "ItemStatus",
    "LIFECYCLE_FAMILY",
    "LIFECYCLE_SCOPE",
    "TaskStatus",
    # terminal/exceptional frozensets
    "EXCEPTIONAL",
    "TASK_TERMINAL_SUCCESS",
    "TERMINAL",
    "TERMINAL_FAILURE",
    "TERMINAL_SUCCESS",
    # validation + terminal-state predicates
    "is_exceptional",
    "is_task_terminal_success",
    "is_terminal",
    "is_terminal_failure",
    "is_terminal_success",
    "is_valid_epic_status",
    "is_valid_issue_status",
    "is_valid_item_status",
    "is_valid_task_status",
    # ordered status collections + progression helpers
    "ALL_EPIC_STATUSES",
    "ALL_ISSUE_STATUSES",
    "ALL_ITEM_STATUSES",
    "ALL_TASK_STATUSES",
    "BOARD_COLUMN_ORDER",
    "EPIC_PROGRESSION",
    "ISSUE_PROGRESSION",
    "PRE_IMPLEMENTATION_STATUSES",
    "epic_progression_index",
    "is_epic_forward_transition",
    "is_forward_transition",
    "progression_index",
    # SQL fragment helpers + display label
    "display_label",
    "sql_task_terminal_success_list",
    "sql_terminal_failure_list",
    "sql_terminal_list",
    "sql_terminal_success_list",
]
