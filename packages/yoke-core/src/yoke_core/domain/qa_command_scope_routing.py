"""Where each class of verification runs, as the project declares it.

Two of the registered verification scopes are the repository's own test suite,
which a CI workflow already runs on every pull request. The other two assert
against a deployed site behind a base URL — and whether CI can reach that site
is a fact about the project, not about the scope. A publicly reachable site can
be checked from CI; one behind a private network cannot. Asserting either
answer for every project is what left a project unable to run its own
post-deploy suite anywhere: the credentials that suite needs existed only as CI
secrets, so the machine was the one place it could not work.

So the scope table keeps a default, and a project may override it by naming the
workflow that runs a scope. Naming a workflow *is* the declaration that the
scope is routable there — the routing decision was already "did a workflow
name resolve?", so one mechanism answers both questions and no second
redundant flag can drift out of agreement with it.

A project that declares nothing keeps the default, which is why adding this
costs existing projects no edit.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.db_helpers import query_scalar
from yoke_core.domain.projects_seed_ci_workflow import CI_WORKFLOW_CAPABILITY_TYPE

#: Key inside the ``ci_workflow_file`` capability's settings document mapping a
#: verification scope to the workflow that runs it. The document is untyped
#: JSON, so a later value shape — an object naming a non-GitHub runner rather
#: than a bare filename — needs no schema change to express.
SCOPE_WORKFLOWS_KEY = "scope_workflows"

#: Key naming the project's default workflow: the one that runs the scopes
#: already routable without a per-scope declaration.
DEFAULT_WORKFLOW_KEY = "workflow_file"


def capability_settings(conn: Any, project_id: int) -> dict[str, Any]:
    """Return the project's ``ci_workflow_file`` settings document.

    One read serves both the default workflow and the per-scope map, because
    both live in the same document and every caller needs at most both.
    """
    marker = "%s" if _is_postgres(conn) else "?"
    raw = query_scalar(
        conn,
        "SELECT COALESCE(settings, '{}') FROM project_capabilities "
        f"WHERE project_id={marker} AND type={marker}",
        (int(project_id), CI_WORKFLOW_CAPABILITY_TYPE),
    )
    if not raw:
        return {}
    try:
        settings = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return settings if isinstance(settings, dict) else {}


def default_workflow(settings: dict[str, Any]) -> str:
    """The workflow a project runs for scopes routable without a declaration."""
    return str(settings.get(DEFAULT_WORKFLOW_KEY) or "").strip()


def scope_workflow(
    settings: dict[str, Any],
    *,
    scope: str,
    default_routable: bool,
) -> str:
    """Return the workflow that runs *scope*, or empty for the local runner.

    A scope the project maps explicitly runs the workflow it names, whatever
    the scope table's default says — that mapping is the project telling Yoke
    this class of verification is reachable from CI. A scope the project does
    not map falls back to the default workflow when the scope is routable by
    default, and to the local runner otherwise, which is exactly today's
    behavior for a project that declares nothing.
    """
    declared = settings.get(SCOPE_WORKFLOWS_KEY)
    if isinstance(declared, dict):
        mapped = str(declared.get(scope) or "").strip()
        if mapped:
            return mapped
    return default_workflow(settings) if default_routable else ""


def workflow_for_scope(
    conn: Any,
    *,
    project_id: int,
    scope: str,
    default_routable: bool,
) -> str:
    """Resolve *scope*'s workflow for one project, reading settings once."""
    return scope_workflow(
        capability_settings(conn, int(project_id)),
        scope=scope,
        default_routable=default_routable,
    )


def _is_postgres(conn: Any) -> bool:
    from yoke_core.domain import db_backend

    return db_backend.connection_is_postgres(conn)


__all__ = [
    "DEFAULT_WORKFLOW_KEY",
    "SCOPE_WORKFLOWS_KEY",
    "capability_settings",
    "default_workflow",
    "scope_workflow",
    "workflow_for_scope",
]
