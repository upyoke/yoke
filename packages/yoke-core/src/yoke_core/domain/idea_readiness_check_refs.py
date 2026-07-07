"""Dotted-reference classification helpers for idea_readiness_check.

Detects command-form module references and planned path-claim targets
that should not be treated as existing-function references by the
readiness checker.  Sibling pattern mirrors idea_readiness_check_rg.py.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional, Set, Tuple

from yoke_core.domain import db_backend

_PACKAGE_SOURCE_ROOTS = {
    "yoke_core": Path("packages/yoke-core/src"),
    "yoke_cli": Path("packages/yoke-cli/src"),
    "yoke_harness": Path("packages/yoke-harness/src"),
}


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def function_refs_to_verify(spec_text: str) -> Set[Tuple[str, str]]:
    """Return ``(full_path, func_name)`` refs paired with edit verbs."""
    ref = (
        r"`?((?:runtime\.api|yoke_core|yoke_cli|yoke_harness)"
        r"[\w\.]+\.([a-z_][a-z_0-9]*))`?"
    )
    verbs = (
        r"modify|modifies|extend|extends|edit|edits|wrap|wraps|"
        r"add behavior to|adds behavior to"
    )
    patterns = [
        re.compile(
            rf"{ref}[^\n.]{{0,120}}\b(?:{verbs})\b",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?:{verbs})\b[^\n.]{{0,120}}{ref}",
            re.IGNORECASE,
        ),
    ]
    out: Set[Tuple[str, str]] = set()
    for pattern in patterns:
        for match in pattern.finditer(spec_text):
            full_path = match.group(1)
            func_name = match.group(2)
            out.add((str(full_path), str(func_name)))
    return out


def is_module_or_planned_ref(
    full_path: str,
    item_id: int,
    conn: Optional[Any],
    repo_root: Optional[Path] = None,
) -> bool:
    """Return True when full_path should NOT be treated as an
    existing-function reference.

    Two carve-outs:
    1. The module portion (all but the last dotted segment) resolves
       to a package directory on disk — meaning full_path is a
       package-submodule invocation rather than a function reference.
       e.g. ``yoke_core.tools.watch_tail`` resolves through
       ``packages/yoke-core/src/yoke_core/tools/``, so
       ``watch_tail`` is a submodule, not a function.
    2. The full dotted path maps to a pre-observation path-claim
       target for item_id — the spec references a file that is
       registered as a planned or tentative implementation surface
       (materialization_state in {'planned','tentative'}). Tentative
       coverage rides the same readiness suppression as planned: the
       declared but not-yet-implemented file is a known forward
       reference, not an unresolved function.
    """
    if "." not in full_path:
        return False
    module_dotted = full_path.rsplit(".", 1)[0]
    # Check 1: module portion resolves to a package directory.
    root = repo_root or _resolve_repo_root()
    if any(
        candidate.is_dir()
        for candidate in _module_dir_candidates(root, module_dotted)
    ):
        return True
    # Check 2: full dotted path maps to a pre-observation claim target.
    if conn is not None and item_id:
        try:
            p = _p(conn)
            for candidate in module_file_candidates(root, full_path):
                rel = str(candidate.relative_to(root))
                row = conn.execute(
                    "SELECT 1 FROM path_claim_targets pct "
                    "JOIN path_claims pc ON pc.id = pct.claim_id "
                    "JOIN path_targets pt ON pt.id = pct.target_id "
                    f"WHERE pc.item_id = {p} "
                    "  AND pc.state IN ('planned', 'active', 'blocked') "
                    "  AND pt.materialization_state IN "
                    "('planned', 'tentative') "
                    f"  AND pt.path_string = {p}",
                    (item_id, rel),
                ).fetchone()
                if row:
                    return True
        except db_backend.operational_error_types(conn):
            pass
    return False


def _resolve_repo_root() -> Path:
    from yoke_core.api.repo_root import find_repo_root

    return find_repo_root(Path(__file__))


def module_file_candidates(repo_root: Path, module_dotted: str) -> tuple[Path, ...]:
    return tuple(path.with_suffix(".py") for path in _module_candidates(
        repo_root, module_dotted,
    ))


def _module_dir_candidates(repo_root: Path, module_dotted: str) -> tuple[Path, ...]:
    return _module_candidates(repo_root, module_dotted)


def _module_candidates(repo_root: Path, module_dotted: str) -> tuple[Path, ...]:
    rel = Path(*module_dotted.split("."))
    package_root = _PACKAGE_SOURCE_ROOTS.get(module_dotted.split(".", 1)[0])
    if package_root is not None:
        return (repo_root / package_root / rel,)
    return (repo_root / rel,)
