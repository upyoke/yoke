"""Canonical schema cheat sheet for the agent-context packet generator.

Pure data sibling of :mod:`schema_api_context_seed`. Holds the curated
``CANONICAL_TABLES`` dict by combining per-topic siblings. The packet
renderer in :mod:`yoke_core.domain.schema_api_context` reconciles
each entry against live catalog introspection at packet-build time.

Topic-scoped siblings (added 2026-05-14 to keep this module under the
350-line authored-file cap while preserving the ``CANONICAL_TABLES``
public export):

- :mod:`schema_api_context_tables_core` — items, epic_tasks,
  epic_dispatch_chains, epic_progress_notes, item_dependencies, events.
- :mod:`schema_api_context_tables_claims` — harness_sessions,
  work_claims, path_claims, path_claim_targets, path_targets,
  path_claim_amendments, actors, actor_labels.
- :mod:`schema_api_context_tables_auth` — roles, permissions,
  role_permissions, actor_project_roles, organizations, actor_org_roles.
- :mod:`schema_api_context_tables_qa` — qa_requirements, qa_runs.
- :mod:`schema_api_context_tables_project` — projects, project_structure.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations

from yoke_core.domain.schema_api_context_tables_auth import (
    AUTH_TABLES,
)
from yoke_core.domain.schema_api_context_tables_claims import (
    CLAIMS_TABLES,
)
from yoke_core.domain.schema_api_context_tables_core import (
    CORE_TABLES,
)
from yoke_core.domain.schema_api_context_tables_project import (
    PROJECT_TABLES,
)
from yoke_core.domain.schema_api_context_tables_python_helpers import (
    PYTHON_HELPERS_TABLES,
)
from yoke_core.domain.schema_api_context_tables_qa import (
    QA_TABLES,
)


CANONICAL_TABLES: dict[str, dict] = {
    **CORE_TABLES,
    **CLAIMS_TABLES,
    **AUTH_TABLES,
    **QA_TABLES,
    **PROJECT_TABLES,
    **PYTHON_HELPERS_TABLES,
}


__all__ = ["CANONICAL_TABLES"]
