"""The authored-file line limit is stated once, in ``file_line_policy``.

Every check, hint and message resolves ``file_line_limit`` through
``project_limit``; a literal default anywhere else would drift from the
setting. This guard scans the shipped product surfaces for the default's
digits and fails on any match outside the policy module.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from yoke_contracts.project_contract.file_line_policy import DEFAULT_LIMIT

REPO_ROOT = Path(__file__).resolve().parents[2]
SCOPES = (
    ":(glob)packages/*/src/**", "runtime/agents", "runtime/harness", "docs/public",
)
POLICY_MODULE = (
    "packages/yoke-contracts/src/yoke_contracts/project_contract/file_line_policy.py"
)
_EXCLUDED_PARTS = {"build", "tests", "fixtures", "archive", "evidence"}
_LITERAL = re.compile(rf"(?<![\w.,]){DEFAULT_LIMIT}(?![\w.,])")


def _in_scope(rel: str) -> bool:
    path = Path(rel)
    if rel == POLICY_MODULE or path.name.startswith("test_"):
        return False
    return not any(
        part in _EXCLUDED_PARTS or part.endswith(".egg-info") for part in path.parts
    )


def literal_hits(root: Path, paths: list[str]) -> list[str]:
    """Return ``path:line`` for each in-scope line naming the default limit."""
    hits: list[str] = []
    for rel in paths:
        if not _in_scope(rel):
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if _LITERAL.search(line):
                hits.append(f"{rel}:{number}: {line.strip()}")
    return hits


def _tracked(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--", *SCOPES],
        check=True, capture_output=True, text=True,
    ).stdout
    return [line for line in out.splitlines() if line]


def test_repository_states_the_limit_only_in_the_policy_module() -> None:
    hits = literal_hits(REPO_ROOT, _tracked(REPO_ROOT))
    assert not hits, (
        "the default line limit appears as a literal; resolve it through "
        "project_limit(repo_root) or name `file_line_limit` instead:\n"
        + "\n".join(hits)
    )


def test_guard_fails_when_a_literal_is_reintroduced(tmp_path: Path) -> None:
    rel = "packages/yoke-core/src/yoke_core/domain/example.py"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_text(f"if lines > {DEFAULT_LIMIT}:\n    pass\n")
    (tmp_path / POLICY_MODULE).parent.mkdir(parents=True)
    (tmp_path / POLICY_MODULE).write_text(f"DEFAULT_LIMIT = {DEFAULT_LIMIT}\n")
    hits = literal_hits(tmp_path, [rel, POLICY_MODULE])
    assert hits == [f"{rel}:1: if lines > {DEFAULT_LIMIT}:"]


def test_guard_ignores_larger_numbers_and_excluded_paths(tmp_path: Path) -> None:
    rel = "docs/public/page.md"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_text(f"{DEFAULT_LIMIT}0 bytes and 1,{DEFAULT_LIMIT} rows\n")
    assert literal_hits(tmp_path, [rel, "runtime/harness/test_x.py"]) == []
