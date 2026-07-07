"""Advisory hints for symlinked File Budget paths.

The readiness gate is blocking only for correctness issues. Symlink
authoring drift is different: registration already claims both the
symlink and canonical target, but the human-readable File Budget should
converge on the canonical name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from yoke_core.domain.file_budget_paths import extract_file_budget_paths
from yoke_core.domain.path_claims_resolve import (
    SYMLINK_CANONICALIZED,
    expand_symlinks_to_canonical,
)

ADVISORY_CODE = "SYMLINK_CANONICAL_HINT"


def collect_symlink_advisories(
    spec_text: str,
    *,
    repo_root: Path,
) -> List[Dict[str, Any]]:
    """Return non-blocking hints for symlink paths in the File Budget."""
    advisories: List[Dict[str, Any]] = []
    for path in extract_file_budget_paths(spec_text):
        _, decisions = expand_symlinks_to_canonical([path], project_root=repo_root)
        for decision in decisions:
            if (
                decision.reason == SYMLINK_CANONICALIZED
                and decision.canonical_path
            ):
                advisories.append({
                    "code": ADVISORY_CODE,
                    "message": (
                        f"`{decision.symlink_path}` is a symlink to "
                        f"`{decision.canonical_path}`; Yoke will claim both "
                        f"— list `{decision.canonical_path}` in the File Budget "
                        "so the human-readable surface matches."
                    ),
                    "remediation": (
                        f"Prefer `{decision.canonical_path}` as the File "
                        f"Budget entry for this edit surface."
                    ),
                    "context": {
                        "symlink_path": decision.symlink_path,
                        "canonical_path": decision.canonical_path,
                    },
                })
                break
    return advisories


__all__ = ["ADVISORY_CODE", "collect_symlink_advisories"]
