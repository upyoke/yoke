"""Domain-module dispatch tables and Python in-process dispatch helpers.

Owns the static dispatch maps used by the db_router entry-point — the
domain-name → Python-module table, the items read/write subcommand
classifiers — and the helpers that import a target module and call its
``main(argv)`` entrypoint with normalized exit codes.
"""

from __future__ import annotations

import importlib
import sys
from typing import Dict, FrozenSet, List


#: Map a DB-router domain name to the canonical Python module that owns
#: its semantics. Each target module exposes ``main(argv=None)`` and
#: accepts the current db_router subcommand grammar.
_DOMAIN_PY_MODULES: Dict[str, str] = {
    "epic":              "yoke_core.domain.epic",
    "shepherd":          "yoke_core.domain.shepherd",
    "ouroboros":         "yoke_core.domain.ouroboros",
    "projects":          "yoke_core.domain.projects",
    "project-structure": "yoke_core.domain.project_structure",
    "release":           "yoke_core.domain.release_notes",
    "flows":             "yoke_core.domain.flow",
    "events":            "yoke_core.domain.events_crud",
    "runs":              "yoke_core.domain.deployment_runs",
    "envs":              "yoke_core.domain.ephemeral_env",
    "qa":                "yoke_core.domain.qa",
    "harness-sessions":  "runtime.harness.harness_sessions",
    "sections":          "yoke_core.domain.sections",
    "path-claims":       "yoke_core.domain.path_claims_dispatch",
}


#: Items read subcommands — route in-process to ``query_items_cli``.
_ITEMS_READ_SUBCMDS: FrozenSet[str] = frozenset(
    {"get", "list", "count", "row", "progress", "render"}
)


#: Items write subcommands — route to the Python-owned backlog CLI parser.
_ITEMS_WRITE_SUBCMDS: FrozenSet[str] = frozenset(
    {
        "add",
        "update",
        "batch-update",
        "rebuild-board",
        "sync-item",
        "sync-labels",
        "sync-body",
        "ingest-body",
        "close",
        "close-issue",
        "post-comment",
        "dedup-search",
        "get-next-id",
        "freeze",
        "thaw",
        "block",
        "unblock",
    }
)


def _dispatch_python_module(module_name: str, argv: List[str]) -> int:
    """Import *module_name* and call ``main(argv)``, propagating exit codes.

    Matches the shell router's ``exec python3 -m <module> "$@"`` contract
    but keeps the call in-process for speed. Each target domain module
    exposes ``main(argv=None)``; this helper normalizes ``SystemExit``,
    ``int`` return values, and ``None`` return values to an int exit code.
    """
    # Lazy import to avoid the circular at module load time —
    # db_router imports from db_router_dispatch at top-level for re-export.
    from yoke_core.cli.db_router import _repo_root

    repo_root = _repo_root()
    root_str = str(repo_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    try:
        mod = importlib.import_module(module_name)
    except ImportError as exc:
        print(
            f"Error: failed to import '{module_name}': {exc}",
            file=sys.stderr,
        )
        return 1
    try:
        result = mod.main(argv)
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            return code
        if code is None:
            return 0
        print(str(code), file=sys.stderr)
        return 1
    if isinstance(result, int):
        return result
    return 0


def _dispatch_module_function(module_name: str, function_name: str, argv: List[str]) -> int:
    """Import *module_name* and call *function_name*(argv), normalizing exits."""
    # Lazy import to avoid the circular at module load time —
    # db_router imports from db_router_dispatch at top-level for re-export.
    from yoke_core.cli.db_router import _repo_root

    repo_root = _repo_root()
    root_str = str(repo_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    try:
        mod = importlib.import_module(module_name)
    except ImportError as exc:
        print(
            f"Error: failed to import '{module_name}': {exc}",
            file=sys.stderr,
        )
        return 1
    target = getattr(mod, function_name, None)
    if target is None:
        print(
            f"Error: '{module_name}' has no callable '{function_name}'",
            file=sys.stderr,
        )
        return 1
    try:
        result = target(argv)
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            return code
        if code is None:
            return 0
        print(str(code), file=sys.stderr)
        return 1
    if isinstance(result, int):
        return result
    return 0
