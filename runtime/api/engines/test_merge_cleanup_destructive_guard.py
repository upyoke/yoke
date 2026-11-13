"""Static guard against destructive merge-lane cleanup primitives.

The forced branch delete is stronger than the git safety it replaces, so it
is fenced in exactly one module: ``branch_landed_evidence`` runs it only
behind that module's landing proof, which is the reading ``git branch -d``
cannot make. Lane trees are deleted only through the tombstone removal in
``worktree_removal``. No merge-lifecycle module issues its own recursive
delete.
"""

from __future__ import annotations

import ast
from pathlib import Path


def _engine_sources() -> list[Path]:
    root = (
        Path(__file__).resolve().parents[3]
        / "packages"
        / "yoke-core"
        / "src"
        / "yoke_core"
        / "engines"
    )
    names = (
        "merge_worktree*.py",
        "merge_landed*.py",
        "done_transition*.py",
        "branch_landed_evidence.py",
    )
    return sorted({path for pattern in names for path in root.glob(pattern)})


def test_merge_lifecycle_has_no_forced_ref_or_worktree_deletion():
    violations: list[str] = []
    for path in _engine_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.List, ast.Tuple)):
                literals = {
                    value.value
                    for value in node.elts
                    if isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                }
                if {"branch", "-D"}.issubset(literals):
                    if path.name != "branch_landed_evidence.py":
                        violations.append(f"{path.name}:{node.lineno}: branch -D")
                if {"worktree", "remove", "--force"}.issubset(literals):
                    violations.append(
                        f"{path.name}:{node.lineno}: forced worktree removal"
                    )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "rmtree"
            ):
                violations.append(f"{path.name}:{node.lineno}: rmtree")

    assert violations == []
