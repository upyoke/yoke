"""Typed entry-surface authorization for work-item creation."""

from __future__ import annotations

import os
from typing import Optional

from yoke_core.domain import db_backend
from yoke_core.domain.workflow_runtime import WorkflowRuntime

ITEM_ENTRY_SURFACE_ENV = "YOKE_ITEM_ENTRY_SURFACE"
ENTRY_SURFACE_HARNESS_SKILL = "harness_skill"

MISSING_ENTRY_SURFACE_MESSAGE = (
    "Work-item creation requires a typed entry surface. Use the workflow's "
    "registered web form, CLI, harness skill, or promotion operation."
)

#: Surfaces that render the operator execution-instruction blocks to the
#: filer themselves (the web form) or carry an already-executed item's
#: attestation forward (promotion), so neither re-attests at creation.
EXECUTION_INSTRUCTIONS_EXEMPT_SURFACES = frozenset({"web_form", "promotion"})

#: Placeholder for a create that never named its project, so the refusal
#: still teaches the shape of the required read.
UNNAMED_PROJECT_TOKEN = "<the project you are filing in>"


def _dsn_dbname(dsn: str) -> Optional[str]:
    """Return the database a libpq key/value DSN actually connects to.

    A DSN may carry ``dbname=`` more than once — test fixtures append a
    disposable database onto the cluster DSN rather than rewriting it —
    and libpq honors the LAST occurrence. Reading the first one names a
    database the connection never opens, which silently reported every
    disposable test database as live authority.
    """
    dbname: Optional[str] = None
    for part in dsn.split():
        if part.startswith("dbname="):
            dbname = part.split("=", 1)[1]
    return dbname


def is_test_isolated_database() -> bool:
    """Return whether the active Postgres authority is a disposable test DB."""
    dbname = _dsn_dbname(os.environ.get(db_backend.PG_DSN_ENV, ""))
    return bool(
        dbname and dbname.startswith(db_backend.POSTGRES_TEST_DB_PREFIX)
    )


def is_test_isolation(db_path: Optional[str] = None) -> bool:
    """Return whether a path-shaped token is backed by a disposable DB."""
    if not db_path:
        return False
    return is_test_isolated_database()


def resolve_entry_surface(entry_surface: Optional[str] = None) -> Optional[str]:
    """Resolve an explicit entry surface or its subprocess environment form."""
    value = entry_surface or os.environ.get(ITEM_ENTRY_SURFACE_ENV)
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def enforce_item_entry_allowed(
    *,
    workflow: WorkflowRuntime,
    entry_surface: Optional[str] = None,
    dry_run: bool = False,
    db_path: Optional[str] = None,
) -> Optional[str]:
    """Return an error when creation is not allowed through this surface."""
    resolved = resolve_entry_surface(entry_surface)
    if resolved is None:
        if dry_run or is_test_isolation(db_path):
            return None
        return MISSING_ENTRY_SURFACE_MESSAGE
    if workflow.allows_entry_surface(resolved):
        return None
    return (
        f"Workflow {workflow.workflow_id}@{workflow.version} does not allow "
        f"the {resolved!r} entry surface."
    )


def execution_instructions_refusal_message(
    *, workflow: str, project: Optional[str] = None,
) -> str:
    """Return the refusal that names this create's own retrieval command."""
    return (
        "Retrieve the operator execution instructions first: yoke workflow "
        f"execution-instruction resolve --workflow {workflow} --project "
        f"{project or UNNAMED_PROJECT_TOKEN} — then refile with "
        "--execution-instructions-considered"
    )


def enforce_execution_instructions_considered(
    *,
    workflow: str,
    project: Optional[str] = None,
    entry_surface: Optional[str] = None,
    considered: bool = False,
    dry_run: bool = False,
) -> Optional[str]:
    """Return an error when a non-web filer has not attested the read.

    The attestation is deliberately a bare boolean: it records that this
    filer retrieved the operator execution-instruction blocks for the
    target workflow and project before authoring, and nothing more. No
    content hash, no staleness window — a filer who read stale
    instructions is a different problem from one who never read any.

    Surfaces that render the blocks themselves stay exempt, as do
    previews and disposable test databases, which is exactly the
    exemption set the typed entry-surface gate already applies.
    """
    if considered:
        return None
    resolved = resolve_entry_surface(entry_surface)
    if resolved is None or resolved in EXECUTION_INSTRUCTIONS_EXEMPT_SURFACES:
        return None
    if dry_run or is_test_isolated_database():
        return None
    return execution_instructions_refusal_message(
        workflow=workflow, project=project,
    )


__all__ = [
    "ENTRY_SURFACE_HARNESS_SKILL",
    "EXECUTION_INSTRUCTIONS_EXEMPT_SURFACES",
    "ITEM_ENTRY_SURFACE_ENV",
    "MISSING_ENTRY_SURFACE_MESSAGE",
    "UNNAMED_PROJECT_TOKEN",
    "enforce_execution_instructions_considered",
    "enforce_item_entry_allowed",
    "execution_instructions_refusal_message",
    "is_test_isolated_database",
    "is_test_isolation",
    "resolve_entry_surface",
]
