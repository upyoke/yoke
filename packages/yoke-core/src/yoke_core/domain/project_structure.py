"""Project Structure aggregate — constitution for project-wide declared structure.

Defines one project-wide unversioned aggregate with a frozen attachment
grammar, multiplicity vocabulary, coherence model, and imperative op-list
write contract. Instantiates every family under that constitution.

Tables owned here (created by :func:`cmd_init`):

* ``project_structure`` — family entries with identity
  ``(project_id, family, attachment_value, entry_key)``. ``entry_key``
  defaults to the empty-string sentinel for singleton families so the
  UNIQUE constraint collapses correctly.

CLI usage::

    python3 -m yoke_core.domain.project_structure <subcmd> [args...]

Subcommands::

    init                                    Create/upgrade tables (idempotent)
    get <project-id> [--family F]           Whole structure or family slice
    patch <project-id> (--stdin|--ops-file) Apply an op list atomically
    seed <project-id>                       Seed legible default entries
    family-list                             Print the frozen family vocabulary

Exit codes: 0 success, 1 error, 2 usage.
"""

from __future__ import annotations

import sys
import json
from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.projects_restart_schema import _projects_table_sql

# When invoked as ``python3 -m yoke_core.domain.project_structure`` Python
# loads this file as ``__main__``. Submodule imports below resolve back to
# ``yoke_core.domain.project_structure`` by qualified name; without the
# alias here Python would re-import the file under that name, producing two
# distinct module objects and a circular-import failure on the re-entry.
sys.modules.setdefault("yoke_core.domain.project_structure", sys.modules[__name__])


# ---------------------------------------------------------------------------
# Constitution: attachment algebra, multiplicity vocabulary, and family
# vocabulary.
# ---------------------------------------------------------------------------

#: Attachment branches per the constitution's closed attachment algebra.
ATTACHMENT_BRANCHES: Tuple[str, ...] = ("project", "path_selector")

#: Valid ``path_selector`` kinds per the constitution's closed attachment
#: algebra.
PATH_SELECTOR_KINDS: Tuple[str, ...] = ("exact", "glob", "tree")

#: Multiplicity vocabulary per the constitution — closed and orthogonal to
#: attachment.
MULTIPLICITIES: Tuple[str, ...] = ("singleton", "keyed_set")

#: Sentinel token for the ``project`` attachment branch per the constitution's
#: identity derivation.
PROJECT_ATTACHMENT_TOKEN: str = "project"

#: Empty-string sentinel for NULL-like identity slots (normalizes UNIQUE).
EMPTY_SLOT: str = ""


#: All families fully frozen by the Project Structure constitution.
#:
#: Each entry declares the family's attachment branch, multiplicity, and
#: optional branch-lock (``locked_kind``).  ``locked_kind`` is None when the
#: family's path_selector branch admits multiple kinds per entry; otherwise
#: it names the only kind the family accepts.
NET_NEW_FAMILIES: Dict[str, Dict[str, Optional[str]]] = {
    "areas": {
        "attachment": "project",
        "multiplicity": "keyed_set",
        "locked_kind": None,
    },
    "mappings": {
        "attachment": "path_selector",
        "multiplicity": "singleton",
        "locked_kind": "glob",
    },
    "test_roots": {
        "attachment": "path_selector",
        "multiplicity": "keyed_set",
        "locked_kind": "tree",
    },
    "verification_profiles": {
        "attachment": "project",
        "multiplicity": "keyed_set",
        "locked_kind": None,
    },
    "ownership_defaults": {
        "attachment": "path_selector",
        "multiplicity": "singleton",
        "locked_kind": "tree",
    },
    "integration_targets": {
        "attachment": "project",
        "multiplicity": "keyed_set",
        "locked_kind": None,
    },
    # ``command_definitions`` uses project attachment, keyed-set multiplicity,
    # and scope-keyed entries.
    "command_definitions": {
        "attachment": "project",
        "multiplicity": "keyed_set",
        "locked_kind": None,
    },
    # ``deploy_defaults`` holds the ticket-level deployment-flow default for
    # a project. Singleton per project — at most one default flow. Absence is
    # a valid "no project default" state; callers treat it as "infer or ask".
    "deploy_defaults": {
        "attachment": "project",
        "multiplicity": "singleton",
        "locked_kind": None,
    },
    # ``merge_verification`` holds the project's pre-merge verification
    # policy: command plus timeout budget. Singleton per project — at most
    # one policy. Absence (no row) is a valid state meaning "no merge command
    # configured"; the merge engine emits an explicit skip log line in that
    # case. Distinct from ``command_definitions`` so the merge gate never
    # leaks into agent test surfaces (Tester dispatch, doctor health checks,
    # stale-string discovery) by construction.
    "merge_verification": {
        "attachment": "project",
        "multiplicity": "singleton",
        "locked_kind": None,
    },
    # ``context_routing`` holds the project's context-routing entries:
    # one reserved ``entry_key="always"`` for the project-wide always-included
    # docs, plus zero-or-more topic-keyed entries (one per topic name) whose
    # docs are added when the topic matches. Payload is ``{"docs": [str, ...]}``
    # with a non-empty list of project-relative file path strings. Keyed-set
    # per project — entries are independent, removable individually.
    "context_routing": {
        "attachment": "project",
        "multiplicity": "keyed_set",
        "locked_kind": None,
    },
    # ``architecture_model`` holds the project's architecture-fitness map:
    # domains, layers, allowed/forbidden edges, and cross-cutting entrypoints.
    # Singleton per project — at most one model per project. Absence means
    # "no architecture model declared"; the architecture HCs self-skip for
    # such projects (they cannot evaluate edge legality without a model).
    "architecture_model": {
        "attachment": "project",
        "multiplicity": "singleton",
        "locked_kind": None,
    },
}


#: Closed scope vocabulary for the ``command_definitions`` family. Mirrored
#: in :mod:`yoke_core.domain.command_definitions` so consumers that only
#: need the read surface don't have to pull in the full Project Structure
#: module.
COMMAND_DEFINITIONS_SCOPES: Tuple[str, ...] = ("quick", "full", "e2e", "smoke")


#: Reserved ``entry_key`` for the project-wide always-included docs in the
#: ``context_routing`` family. Every other ``entry_key`` is a topic name.
CONTEXT_ROUTING_ALWAYS_KEY: str = "always"


ALL_FAMILIES: Tuple[str, ...] = tuple(sorted(NET_NEW_FAMILIES))


# ---------------------------------------------------------------------------
# Exceptions (domain-level; CLI maps these to exit codes)
# ---------------------------------------------------------------------------


class ProjectStructureError(Exception):
    """Base class for Project Structure domain errors."""


class UsageError(ProjectStructureError):
    """CLI argument or op-shape misuse."""


class ValidationError(ProjectStructureError):
    """Envelope or payload validation failure."""


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def _connect(db_path: Optional[str]) -> Any:
    return connect(db_path)


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def create_project_structure_tables(conn) -> None:
    """Create the Project Structure tables on an existing connection. Idempotent.

    The single DDL owner for ``project_structure``; both :func:`cmd_init`
    (own-connection) and connection-passing callers (backend-aware test
    fixtures that build the minimal schema on one facade connection) route
    here so the DDL is never duplicated.
    """
    execute_schema_script(
        conn,
        _projects_table_sql(if_not_exists=True) + """
        CREATE TABLE IF NOT EXISTS project_structure (
          id INTEGER PRIMARY KEY,
          project_id INTEGER NOT NULL REFERENCES projects(id),
          family TEXT NOT NULL,
          attachment_value TEXT NOT NULL,
          attachment_kind TEXT NOT NULL DEFAULT '',
          entry_key TEXT NOT NULL DEFAULT '',
          payload TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(project_id, family, attachment_value, entry_key)
        );
        CREATE INDEX IF NOT EXISTS idx_project_structure_project
          ON project_structure(project_id);
        CREATE INDEX IF NOT EXISTS idx_project_structure_family
          ON project_structure(project_id, family);
        """
    )
    conn.commit()


def cmd_init(db_path: Optional[str] = None) -> None:
    """Create (or upgrade) the Project Structure tables. Idempotent.

    ``project_structure`` is the single unversioned policy/family storage
    table. Mutation history flows through the shared event ledger.
    """
    conn = _connect(db_path)
    try:
        create_project_structure_tables(conn)
    finally:
        conn.close()


def _row_to_entry(row: Any) -> Dict[str, Any]:
    payload = row["payload"] or "{}"
    try:
        parsed = json.loads(payload)
    except (TypeError, ValueError):
        parsed = {}
    entry: Dict[str, Any] = {
        "attachment": row["attachment_value"],
        "payload": parsed,
    }
    if row["attachment_kind"]:
        entry["attachment_kind"] = row["attachment_kind"]
    if row["entry_key"]:
        entry["entry_key"] = row["entry_key"]
    return entry


def read_structure(
    project_id: str,
    family: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Read the whole Project Structure tree, or a single family slice."""
    conn = _connect(db_path)
    try:
        numeric_project_id = resolve_project_id(conn, project_id)
        p = _placeholder(conn)
        if family is not None:
            _require_known_family(family)
            rows = query_rows(
                conn,
                "SELECT attachment_value, attachment_kind, entry_key, payload "
                "FROM project_structure "
                f"WHERE project_id={p} AND family={p} "
                "ORDER BY attachment_value, entry_key",
                (numeric_project_id, family),
            )
            return {
                "project_id": project_id,
                "family": family,
                "entries": [_row_to_entry(r) for r in rows],
            }

        families: Dict[str, List[Dict[str, Any]]] = {
            name: [] for name in NET_NEW_FAMILIES
        }
        rows = query_rows(
            conn,
            "SELECT family, attachment_value, attachment_kind, entry_key, payload "
            "FROM project_structure "
            f"WHERE project_id={p} "
            "ORDER BY family, attachment_value, entry_key",
            (numeric_project_id,),
        )
        for row in rows:
            families.setdefault(row["family"], []).append(_row_to_entry(row))
        return {
            "project_id": project_id,
            "families": families,
        }
    finally:
        conn.close()


from .project_structure_validation import (  # noqa: F401
    _require_known_family,
    _validate_envelope,
    _validate_payload,
)
from .project_structure_write import (  # noqa: F401
    _apply_put,
    _apply_remove,
    _derive_attachment_kind,
    _format_identity,
    _normalize_op,
    apply_patch,
)
from .project_structure_seeds import (  # noqa: F401
    cmd_seed,
)
from .project_structure_cli import (  # noqa: F401
    _build_parser,
    _parse_patch_input,
    cmd_family_list,
    cmd_get,
    cmd_patch,
    cmd_seed_cli,
    main,
)


if __name__ == "__main__":
    sys.exit(main())
