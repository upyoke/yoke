"""Static audit: every ``gh issue create``/``edit`` body mutation in the
runtime API tree must either route through the shared compact-mirror
budget guard or appear in an explicit allowlist with a reason.

A "body mutation" is any code-author-controlled ``--body`` or
``--body-file`` argument passed to ``gh issue create`` or ``gh issue
edit``. The audit walks every live Yoke API/core ``.py`` file, finds
matching call sites, and classifies each as guarded (routes through
:mod:`yoke_core.domain.backlog_github_body_writer` or
:func:`backlog_github_body_budget.select_and_write_body_file`) or
unguarded.

Unguarded sites must be listed in :data:`ALLOWLIST` with a one-line
reason explaining why they are not a full backlog/epic/task body
mirror (e.g., closeout comment, dispatch summary, label-only edit
mistakenly matching the regex).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

import pytest

from yoke_core.api.repo_root import find_repo_root


# Files allowed to mention ``gh issue create``/``edit`` body args without
# the shared writer. Map of repo-relative path -> reason. Keep this list
# small; every entry is a coordination cost.
ALLOWLIST: dict[str, str] = {
    # Tests intentionally exercise raw shapes alongside the shared writer.
    "runtime/api/test_github_issue_body_budget_all_paths.py":
        "this audit module itself contains literal pattern examples",
    "runtime/api/domain/test_backlog_github_body_budget.py":
        "unit tests for the budget guard intentionally exercise the helper directly",
    "runtime/api/test_backlog_github_sync_body_title.py":
        "integration tests intentionally probe typed REST issue-edit shapes",
    "runtime/api/test_backlog_github_sync_done.py":
        "regression test asserts compact-mode selection for sync_done_item",
    "runtime/api/test_backlog_github_backfill_oversized.py":
        "backfill integration tests intentionally invoke typed REST issue-edit shapes",
    "packages/yoke-core/src/yoke_core/domain/backlog_github_repo_migration.py":
        "repo migration creates forwarding issues/comments, not rendered item mirrors",
    "packages/yoke-core/src/yoke_core/engines/doctor_hc_worktrees_gh_repo.py":
        "doctor uses short diagnostic issue bodies, not rendered item mirrors",
}


def _iter_python_files(api_root: Path) -> Iterable[Path]:
    for path in sorted(api_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def _file_uses_shared_writer(source: str) -> bool:
    """Detect import of the shared budget-guarded writer or the lower
    ``select_and_write_body_file`` helper anywhere in the module."""
    return (
        "backlog_github_body_writer" in source
        or "select_and_write_body_file" in source
    )


def _literal_tokens(node: ast.AST) -> list[str]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal_tokens(node.left) + _literal_tokens(node.right)
    if not isinstance(node, (ast.List, ast.Tuple)):
        return []
    tokens: list[str] = []
    for elt in node.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            tokens.append(elt.value)
    return tokens


def _tokens_are_issue_body_mutation(tokens: list[str]) -> bool:
    for idx, token in enumerate(tokens):
        if token != "issue":
            continue
        rest = tokens[idx + 1:]
        return bool(
            rest
            and rest[0] in {"create", "edit"}
            and any(arg in {"--body", "--body-file"} for arg in rest)
        )
    return False


def _has_gh_body_mutation(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(
        _tokens_are_issue_body_mutation(_literal_tokens(node))
        for node in ast.walk(tree)
    )


def test_every_unguarded_gh_body_mutation_is_allowlisted() -> None:
    repo_root = find_repo_root(Path(__file__))
    source_roots = (
        repo_root / "runtime" / "api",
        repo_root / "packages" / "yoke-core" / "src" / "yoke_core",
    )
    for source_root in source_roots:
        assert source_root.is_dir(), f"{source_root.relative_to(repo_root)} missing under {repo_root}"

    offenders: list[tuple[str, str]] = []
    for source_root in source_roots:
        for path in _iter_python_files(source_root):
            rel = path.relative_to(repo_root).as_posix()
            try:
                source = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if not _has_gh_body_mutation(source):
                continue
            if _file_uses_shared_writer(source):
                continue
            if rel in ALLOWLIST:
                continue
            offenders.append((rel, "unguarded gh issue create/edit body mutation"))

    if offenders:
        joined = "\n".join(f"  - {rel}: {reason}" for rel, reason in offenders)
        pytest.fail(
            "Unguarded GitHub issue body mutations detected. Route the body "
            "through yoke_core.domain.backlog_github_body_writer.write_issue_body_via_gh "
            "or backlog_github_body_budget.select_and_write_body_file, "
            "or add the file to ALLOWLIST with a reason proving it is not "
            "a full issue body mirror.\n" + joined,
        )


def test_allowlist_entries_still_exist() -> None:
    """Stale allowlist entries silently mask new unguarded sites once the
    file is renamed or removed. The audit fails when a listed path is no
    longer present.
    """
    repo_root = find_repo_root(Path(__file__))
    missing = [
        rel for rel in ALLOWLIST
        if not (repo_root / rel).is_file()
    ]
    if missing:
        joined = "\n".join(f"  - {rel}" for rel in missing)
        pytest.fail(
            "ALLOWLIST contains paths that no longer exist. Drop them so "
            "future unguarded sites at those paths are not silently "
            "allowed:\n" + joined,
        )


def test_audit_detects_known_python_call_shapes() -> None:
    """Sanity: the audit catches Python list-shaped gh calls, not just shell text."""
    positives = [
        'cmd = ["issue", "create", "--title", "X", "--body-file", "/tmp/x"]',
        'cmd = ["gh", "issue", "create", "--title", "X", "--body", "literal"]',
        'cmd = ["issue", "edit"] + repo_flag + ["123", "--body-file", path]',
        'cmd = ["gh", "issue", "edit", "123", "--body", new_body]',
    ]
    for shape in positives:
        assert _has_gh_body_mutation(shape), f"audit should match: {shape!r}"

    negatives = [
        'cmd = ["issue", "view", "123"]',
        'cmd = ["issue", "close", "123"]',
        'cmd = ["issue", "edit", "123", "--add-label", "x"]',
        'cmd = ["issue", "create", "--title", "X", "--label", "y"]',
        'text = "gh issue create --title X --body literal"',
    ]
    for shape in negatives:
        assert not _has_gh_body_mutation(shape), f"audit should NOT match: {shape!r}"
