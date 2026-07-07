"""Frozen seed data and ``cmd_seed`` for the Project Structure aggregate.

The seeds are ordered lists of op dicts — the same shape :func:`apply_patch`
accepts, minus the ``op`` field (always ``put`` for seeding). This keeps
the seed surface dogfooded against the same write contract operators use.
"""

from __future__ import annotations

from yoke_core.domain.strategy_docs_paths import STRATEGY_DIR_REL

import copy
from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain.project_structure import UsageError, read_structure
from yoke_core.domain.project_structure_write import apply_patch

_YOKE_FULL_TEST_COMMAND = (
    "python3 -m yoke_core.tools.watch_pytest -- "
    "runtime/api/ runtime/harness/ tests/"
)


#: Frozen seed data for projects known to Yoke at constitution-freeze time.
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
        {"family": "mappings", "attachment": "runtime/browser_runtime/**",
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

        # Yoke project-level test commands.
        # ``full`` resolves to the canonical local verification target.
        # ``quick``, ``e2e``, and ``smoke`` are intentionally absent: Yoke is
        # a control-plane CLI, not a deployed service, so there is no real
        # end-to-end suite, no shallow real-stack smoke surface, and no
        # fast-signal subset distinct from ``full`` today. Consumers treat
        # missing scopes as "no command defined".
        {"family": "command_definitions", "attachment": "project",
         "entry_key": "full",
         "payload": {"command": _YOKE_FULL_TEST_COMMAND}},

        # Yoke's delivery deployment flow.
        {"family": "deploy_defaults", "attachment": "project",
         "payload": {"deployment_flow": "yoke-internal"}},

        # Yoke's merge verification policy: intentionally absent.
        # The agent-facing ``full`` command is too slow for Yoke's merge gate.
        # Yoke therefore configures no ``merge_verification`` row; the merge
        # engine logs an explicit
        # "no merge policy configured" line and proceeds without running
        # any project test command. To run a different command at merge
        # time, configure one explicitly via
        # ``python3 -m yoke_core.domain.merge_verification set yoke <cmd>
        # --timeout-seconds <seconds>``. The timeout is part of the project
        # policy; choose a budget that fits the command.

        # Yoke's context routing: project-wide always-included docs. The
        # reserved ``always`` entry_key is the project-wide doc set; yoke
        # defines no topic-keyed entries today.
        {"family": "context_routing", "attachment": "project",
         "entry_key": "always",
         "payload": {"docs": ["CLAUDE.md", "yoke/README.md"]}},
    ],
    "buzz": [
        {"family": "areas", "attachment": "project", "entry_key": "backend",
         "payload": {"description": "Buzz backend — FastAPI + pytest."}},
        {"family": "areas", "attachment": "project", "entry_key": "frontend",
         "payload": {"description": "Buzz web frontend — React/Vite."}},
        {"family": "areas", "attachment": "project", "entry_key": "docs",
         "payload": {"description": "Buzz durable documentation."}},

        {"family": "mappings", "attachment": "app/**",
         "payload": {"area_name": "backend"}},
        {"family": "mappings", "attachment": "web/**",
         "payload": {"area_name": "frontend"}},
        {"family": "mappings", "attachment": "docs/**",
         "payload": {"area_name": "docs"}},

        {"family": "test_roots", "attachment": "app/tests/",
         "entry_key": "backend_tests",
         "payload": {"purpose": "Backend pytest surface."}},
        {"family": "test_roots", "attachment": "web/tests/",
         "entry_key": "frontend_tests",
         "payload": {"purpose": "Frontend vitest + playwright surface."}},

        {"family": "verification_profiles", "attachment": "project",
         "entry_key": "backend_quick",
         "payload": {"test_command": "cd app && .venv/bin/python3 -m pytest tests/ -k 'not live'",
                     "description": "Quick backend signal."}},
        {"family": "verification_profiles", "attachment": "project",
         "entry_key": "frontend_quick",
         "payload": {"test_command": "cd web && npm run test",
                     "description": "Quick frontend signal."}},

        {"family": "ownership_defaults", "attachment": "app/",
         "payload": {"owner": "backend"}},
        {"family": "ownership_defaults", "attachment": "web/",
         "payload": {"owner": "frontend"}},

        {"family": "integration_targets", "attachment": "project",
         "entry_key": "main",
         "payload": {"branch_pattern": "main",
                     "description": "Primary integration branch."}},

        # Buzz project-level test commands.
        # ``e2e`` is intentionally absent — buzz has no real end-to-end
        # suite today; browser integration tests live under ``full``.
        {"family": "command_definitions", "attachment": "project",
         "entry_key": "quick",
         "payload": {"command":
                     'sh app/scripts/setup-venv.sh'
                     ' && cd app && .venv/bin/python3 -m pytest tests/ -k "not live"'
                     ' && cd web && npm run test'}},
        {"family": "command_definitions", "attachment": "project",
         "entry_key": "full",
         "payload": {"command":
                     'sh app/scripts/setup-venv.sh'
                     ' && cd app && .venv/bin/python3 -m pytest tests/ -k "not live"'
                     ' && cd web && npm run test && npm run build'
                     ' && npm run test:browser'}},
        {"family": "command_definitions", "attachment": "project",
         "entry_key": "smoke",
         "payload": {"command": "cd app/web && npm run test:smoke"}},

        # Buzz's merge verification policy: intentionally absent on first
        # deploy. Existing Buzz installs that previously relied on the
        # implicit fallback to ``full``/``quick`` will see the merge
        # engine emit "no merge policy configured" and skip project
        # tests at merge time. To restore an explicit gate, configure one
        # via
        # ``python3 -m yoke_core.domain.merge_verification set buzz <cmd>
        # --timeout-seconds <seconds>``. The timeout is part of the project
        # policy; a typical command is the ``quick`` scope for fast signal.

        # Buzz context routing: project-wide always-included docs plus
        # topic-keyed entries that mirror the previous coarse columns.
        {"family": "context_routing", "attachment": "project",
         "entry_key": "always",
         "payload": {"docs": ["AGENTS.md"]}},
        {"family": "context_routing", "attachment": "project",
         "entry_key": "backend",
         "payload": {"docs": ["docs/API.md", "docs/PIPELINE.md"]}},
        {"family": "context_routing", "attachment": "project",
         "entry_key": "frontend",
         "payload": {"docs": ["docs/DASHBOARD.md"]}},
        {"family": "context_routing", "attachment": "project",
         "entry_key": "testing",
         "payload": {"docs": ["docs/TESTING.md"]}},
        {"family": "context_routing", "attachment": "project",
         "entry_key": "deployment",
         "payload": {"docs": ["docs/VPS-SETUP.md"]}},
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
        return {
            "project_id": project_id,
            "applied_ops": [],
            "note": "seed already complete",
        }

    return apply_patch(
        project_id,
        ops=ops,
        actor="seed",
        db_path=db_path,
    )
