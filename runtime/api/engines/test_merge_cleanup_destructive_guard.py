"""Static guard against destructive merge-lane cleanup primitives.

Two deletions are stronger than the git safety they replace, and each is
fenced in exactly one module: the forced branch delete in
``branch_landed_evidence`` runs only behind that module's landing proof,
which is the reading ``git branch -d`` cannot make, and the recursive
delete in ``merge_worktree_cleanliness`` only removes paths its named-cache
allowlist matched. Every other lane path must reach them through those
modules rather than issuing its own.
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
                if path.name == "merge_worktree_cleanliness.py":
                    # The one permitted recursive delete is fenced by the
                    # explicit disposable-cache allowlist and followed by a
                    # second full cleanliness proof. Its focused tests cover
                    # both known caches and unknown ignored content.
                    continue
                violations.append(f"{path.name}:{node.lineno}: rmtree")

    assert violations == []
