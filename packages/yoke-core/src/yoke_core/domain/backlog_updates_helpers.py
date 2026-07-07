"""Backlog updates helper stable import surface.

Responsibility-named sibling modules own the helper behavior. This module
re-exports that helper surface directly from each canonical owner so test
importers and the `backlog_updates.py` re-export chain resolve through one
compact module.

Sibling layout (each imported directly — no two-hop indirection):

- ``backlog_item_db_writes``                — INSERT / UPDATE row helpers
- ``backlog_session_attribution``           — current-item / session-id env
- ``backlog_status_claim_verification``     — per-write claim verification
- ``backlog_epic_task_cascade``             — cascade epic status to tasks
- ``backlog_db_mutation_gate_runner``       — joint / evidence / polish gate
                                              dispatch + prose-vs-claim check
- ``backlog_file_line_gate_runner``         — file-line lifecycle no-op shim
- ``backlog_authoritative_status_gate``     — composes QA + DB + plan gates
- ``backlog_unsupported_field_writes``      — type / source / deploy_stage writes
- ``backlog_project_issue_migration``       — project change → issue migration

For new code, import directly from the canonical owner sibling.
"""

from __future__ import annotations

from yoke_core.domain.backlog_item_db_writes import (  # noqa: F401
    _insert_item,
    _update_item_field,
    _update_item_multi,
)
from yoke_core.domain.backlog_session_attribution import (  # noqa: F401
    _current_session_id,
    _maybe_set_session_current_item,
)
from yoke_core.domain.backlog_status_claim_verification import (  # noqa: F401
    _verify_status_claim,
)
from yoke_core.domain.backlog_epic_task_cascade import (  # noqa: F401
    _cascade_epic_tasks,
)
from yoke_core.domain.backlog_db_mutation_gate_runner import (  # noqa: F401
    _DB_MUTATION_GATE_TARGETS,
    _PROSE_CHECK_TARGETS,
    _profile_declares_mutation,
    _run_db_mutation_gate,
    _run_prose_vs_claim_check,
)
from yoke_core.domain.backlog_file_line_gate_runner import (  # noqa: F401
    _FILE_LINE_GATE_TARGETS,
    _run_file_line_gate,
)
from yoke_core.domain.backlog_authoritative_status_gate import (  # noqa: F401
    _run_authoritative_status_gate,
)
from yoke_core.domain.backlog_unsupported_field_writes import (  # noqa: F401
    _apply_shell_fallback,
)
from yoke_core.domain.backlog_project_issue_migration import (  # noqa: F401
    _maybe_migrate_project_issue,
)


__all__ = [
    # DB writes
    "_insert_item",
    "_update_item_field",
    "_update_item_multi",
    # Session attribution
    "_current_session_id",
    "_maybe_set_session_current_item",
    # Status claim verification
    "_verify_status_claim",
    # Epic task cascade
    "_cascade_epic_tasks",
    # DB mutation gate runner
    "_DB_MUTATION_GATE_TARGETS",
    "_PROSE_CHECK_TARGETS",
    "_profile_declares_mutation",
    "_run_db_mutation_gate",
    "_run_prose_vs_claim_check",
    # File-line gate runner
    "_FILE_LINE_GATE_TARGETS",
    "_run_file_line_gate",
    # Authoritative status gate (composer)
    "_run_authoritative_status_gate",
    # Unsupported field writes
    "_apply_shell_fallback",
    # Project issue migration
    "_maybe_migrate_project_issue",
]
