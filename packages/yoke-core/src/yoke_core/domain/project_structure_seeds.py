"""Source-owned seed data and ``cmd_seed`` for Project Structure.

The seeds are ordered lists of op dicts — the same shape :func:`apply_patch`
accepts, minus the ``op`` field (always ``put`` for seeding). This keeps
the seed surface dogfooded against the same write contract operators use.
"""

from __future__ import annotations

from yoke_core.domain.strategy_docs_paths import STRATEGY_DIR_REL

import copy
from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.project_structure import UsageError, read_structure
from yoke_core.domain.project_structure_write import apply_patch
from yoke_core.domain.schema_common import _table_exists

_YOKE_FULL_TEST_COMMAND = (
    "python3 -m yoke_core.tools.watch_pytest -- "
    "runtime/api/ runtime/harness/ tests/"
)


#: Seed data for the Yoke control-plane project.
#:
#: The seeds are ordered lists of op dicts — the same shape :func:`apply_patch`
#: accepts, minus the ``op`` field (always ``put`` for seeding).  This keeps
#: the seed surface dogfooded against the same write contract operators use.
_SEEDS: Dict[str, List[Dict[str, Any]]] = {
    "yoke": [
        {"family": "areas", "attachment": "project", "entry_key": "api",
         "payload": {"description": "Yoke core API surface: domain, engines, CLI."}},
        {"family": "areas", "attachment": "project", "entry_key": "harness",
         "payload": {"description": "Harness adapters for Claude and Codex."}},
        {"family": "areas", "attachment": "project", "entry_key": "browser",
         "payload": {"description": "Packaged Browser QA daemon sources; "
                                    "runs from the machine runtime dir."}},
        {"family": "areas", "attachment": "project", "entry_key": "skills",
         "payload": {"description": "Operator skills and command surfaces."}},
        {"family": "areas", "attachment": "project", "entry_key": "strategy",
         "payload": {"description": "Strategy/SML working layer."}},
        {"family": "areas", "attachment": "project", "entry_key": "docs",
         "payload": {"description": "Durable documentation and decisions."}},

        {"family": "mappings", "attachment": "runtime/api/**",
         "payload": {"area_name": "api"}},
        {"family": "mappings", "attachment": "runtime/harness/**",
         "payload": {"area_name": "harness"}},
        {"family": "mappings",
         "attachment": "packages/yoke-harness/src/yoke_harness/browser_runtime/**",
         "payload": {"area_name": "browser"}},
        {"family": "mappings", "attachment": ".agents/skills/yoke/**",
         "payload": {"area_name": "skills"}},
        {"family": "mappings", "attachment": f"{STRATEGY_DIR_REL}/**",
         "payload": {"area_name": "strategy"}},
        {"family": "mappings", "attachment": "docs/**",
         "payload": {"area_name": "docs"}},

        {"family": "test_roots", "attachment": "runtime/api/",
         "entry_key": "api_tests",
         "payload": {"purpose": "Primary pytest surface for Yoke core."}},
        {"family": "test_roots", "attachment": "runtime/harness/",
         "entry_key": "harness_tests",
         "payload": {"purpose": "Harness adapter coverage."}},
        {"family": "test_roots", "attachment": "tests/",
         "entry_key": "product_boundary_tests",
         "payload": {"purpose": "Product boundary and machine-config coverage."}},

        {"family": "verification_profiles", "attachment": "project",
         "entry_key": "default",
         "payload": {"test_command": _YOKE_FULL_TEST_COMMAND,
                     "description": "Canonical verification target."}},

        {"family": "ownership_defaults", "attachment": "runtime/api/",
         "payload": {"owner": "yoke-core"}},

        {"family": "integration_targets", "attachment": "project",
         "entry_key": "main",
         "payload": {"branch_pattern": "main",
                     "description": "Primary integration branch."}},

        # Yoke's delivery deployment flow.
        {"family": "deploy_defaults", "attachment": "project",
         "payload": {"deployment_flow": "yoke-internal"}},

        # Yoke's context routing: project-wide always-included docs. The
        # reserved ``always`` entry_key is the project-wide doc set; yoke
        # defines no topic-keyed entries today.
        {"family": "context_routing", "attachment": "project",
         "entry_key": "always",
         "payload": {"docs": ["CLAUDE.md", "yoke/README.md"]}},
    ],
}


def cmd_seed(project_id: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Seed a project with legible default entries.

    Idempotent per identity: only absent entries are seeded, so re-running
    ``seed`` after operator edits does not clobber them.  Runs through the
    same :func:`apply_patch` surface so the seed path dogfoods the write
    contract.

    Returns the patch result dict on success, or a noop-result dict when
    every seed entry is already present.
    """
    seeds = _SEEDS.get(project_id)
    if seeds is None:
        raise UsageError(
            f"No frozen seed recipe for project '{project_id}'. "
            f"Known seeds: {', '.join(sorted(_SEEDS))}."
        )

    existing = read_structure(project_id, db_path=db_path)
    present: Dict[Tuple[str, str, str], bool] = {}
    for family, entries in existing.get("families", {}).items():
        for entry in entries:
            present[
                (family, entry["attachment"], entry.get("entry_key", ""))
            ] = True

    ops: List[Dict[str, Any]] = []
    for seed in seeds:
        family = seed["family"]
        attachment = seed["attachment"]
        entry_key = seed.get("entry_key", "")
        if (family, attachment, entry_key) in present:
            continue
        op = {"op": "put", **copy.deepcopy(seed)}
        ops.append(op)

    if not ops:
        result = {
            "project_id": project_id,
            "applied_ops": [],
            "note": "seed already complete",
        }
    else:
        result = apply_patch(
            project_id,
            ops=ops,
            actor="seed",
            db_path=db_path,
        )
    if project_id == "yoke":
        conn = connect(path=db_path)
        try:
            if (
                _table_exists(conn, "qa_methods")
                and _table_exists(conn, "qa_plans")
                and _table_exists(conn, "qa_plan_project_defaults")
            ):
                from yoke_core.domain.qa_command_plan_migration import (
                    ensure_registered_command_plan,
                )

                identity = resolve_project(conn, project_id, required=True)
                ensure_registered_command_plan(
                    conn,
                    project_id=int(identity.id),
                    project=identity.slug,
                    scope="full",
                    command=_YOKE_FULL_TEST_COMMAND,
                )
        finally:
            conn.close()
    return result
