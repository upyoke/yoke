"""Postgres-native JSON column SQL fragments.

Callers use :func:`json_get` and :func:`json_set_expr` instead of hand-writing
``jsonb`` operators at every call site.  The returned strings are SQL
fragments for interpolation into larger query strings; the module never
executes SQL.

:data:`JSONB_COLUMNS` enumerates the pre-existing ``TEXT`` columns that carry
JSON payloads and are treated as ``JSONB`` under the Postgres cutover.  Other
Yoke modules import this list rather than maintaining their own copies.

Usage::

    from yoke_core.domain.sql_json import json_get, json_set_expr

    conn.execute(
        f"SELECT {json_get('settings', '$.default_branch')} FROM projects"
    )

    conn.execute(
        f"UPDATE qa_runs SET raw_result = "
        f"{json_set_expr('raw_result', '$.last_verdict', '?')}",
        (verdict,),
    )
"""

from __future__ import annotations

import re
from typing import Mapping, Tuple


def _pg_path(path: str) -> str:
    """Convert a JSON path (``$.a.b`` / ``$.a[0]``) to a Postgres ``text[]``
    path literal (``{a,b}`` / ``{a,0}``)."""
    body = path[1:] if path.startswith("$") else path
    parts = re.findall(r"[^.\[\]]+", body)
    return "{" + ",".join(parts) + "}"


# Pre-existing TEXT columns that carry JSON payloads.  Annotated with
# ``-- -> JSONB on Postgres`` in ``schema.py`` / ``fixtures/backlog.py`` and
# converted to ``JSONB`` during the Postgres cutover.  Pinned per the
# Technical Plan §"JSONB-annotation column enumeration (pinned for pre-existing
# surface)"; deliberately excludes markdown/plain-text columns such as
# ``items.spec``, ``items.design_spec``, ``items.technical_plan``,
# ``items.worktree_plan``, ``items.shepherd_log``, ``items.shepherd_caveats``,
# ``items.test_results``, ``items.deploy_log``, ``epic_progress_notes.body``,
# ``shepherd_verdicts.caveats``, ``ouroboros_entries.body``, and
# ``release_entries.{title,version,category,project}``.
JSONB_COLUMNS: Mapping[str, Tuple[str, ...]] = {
    "events": ("envelope", "anomaly_flags"),
    "items": ("db_mutation_profile", "db_compatibility_attestation"),
    "qa_runs": ("raw_result",),
    "qa_artifacts": ("metadata",),
    "deployment_flows": ("stages",),
    "deployment_runs": ("carried_work", "bound_sources"),
    "migration_audit": ("baseline_verify_result", "author_verify_result"),
    "path_context_values": ("value",),
    "function_call_ledger": ("result",),
    "github_workflow_dispatch_intents": ("inputs",),
    "pack_catalog": ("dependencies_json",),
}


def json_get(column_expr: str, path: str) -> str:
    """Return a SQL fragment that reads ``path`` out of ``column_expr``.

    The JSON-payload TEXT column is cast to ``jsonb`` (empty string coerced to
    NULL first) and read with the Postgres ``#>>`` text-path operator.
    """
    return f"NULLIF({column_expr}, '')::jsonb #>> '{_pg_path(path)}'"


def json_set_expr(column_expr: str, path: str, value_sql: str) -> str:
    """Return a SQL fragment that writes ``value_sql`` into
    ``column_expr`` at ``path``.

    ``value_sql`` is inlined verbatim so callers can pass either a bound
    placeholder (``"?"``) or another SQL expression.  The body is a
    ``jsonb_set(...)::text`` over the cast column (NULL/empty base coalesced
    to ``'{}'``) so the result fits the existing TEXT column.
    """
    return (
        f"jsonb_set(COALESCE(NULLIF({column_expr}, '')::jsonb, '{{}}'::jsonb), "
        f"'{_pg_path(path)}', to_jsonb({value_sql}))::text"
    )


def json_valid_expr(column_expr: str) -> str:
    """Return a SQL fragment that is true when ``column_expr`` holds valid JSON.

    Uses the Postgres 16 ``IS JSON`` predicate directly so callers express the
    check natively instead of leaning on the dialect facade to rewrite SQLite's
    ``json_valid(...)``.  ``NULL IS JSON`` is unknown (the row is excluded by a
    ``WHERE`` / ``CASE WHEN`` test), matching the prior facade output.
    """
    return f"({column_expr} IS JSON)"


def _nul_safe_text(column: str) -> str:
    """Read JSON text through jsonb, keeping unsupported NUL as a control byte.

    JSON text permits escaped NUL; jsonb rejects it. SOH preserves the control
    character classification (including invalid raw JSON inside a preview)
    while domain identifiers remain ASCII. Literal backslash sequences stay.
    """
    pattern = r"(?<!\\)((?:\\\\)*)\\u0000"
    replacement = r"\1\\u0001"
    return (
        f"(CASE WHEN strpos({column}, chr(92) || 'u0000') > 0 THEN "
        f"regexp_replace({column}, '{pattern}', '{replacement}', 'g') "
        f"ELSE {column} END)"
    )


def jsonb_text_expr(column: str) -> str:
    """Read NUL-safe JSON text as jsonb."""
    return _nul_safe_text(column) + "::jsonb"


def json_text_expr(column: str) -> str:
    """Read NUL-safe JSON text without building unrelated jsonb fields."""
    return _nul_safe_text(column) + "::json"


__all__ = [
    "JSONB_COLUMNS",
    "json_get",
    "json_set_expr",
    "json_valid_expr",
    "jsonb_text_expr",
    "json_text_expr",
]
