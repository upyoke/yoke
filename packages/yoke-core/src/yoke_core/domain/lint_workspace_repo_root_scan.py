"""Static scan for direct ``agents_render._repo_root`` references.

Companion to :mod:`yoke_core.domain.lint_workspace_cwd_match`. That
module's PreToolUse Bash hook audits *outer* writer-class invocations
from cross-checkout cwds. The leak shape it closes is one layer
deeper: in-process reader hot paths and test fixtures that import
``_repo_root`` directly and call it without an explicit ``target_root``.
The scan helper here flags non-allowlisted modules that name the symbol
via import, attribute access, or ``mock.patch`` — the structural defense
against the symbol leaking back into reader hot paths via a future
regression.

The helper is a static-scan surface — it does not run as a runtime hook.
Doctor HCs, pre-commit gates, and dedicated regression tests consume it.

The allowlist below is the single canonical Python constant for
this rule. Sibling code paths import :data:`REPO_ROOT_REFERENCE_ALLOWLIST`
rather than maintaining a parallel allowlist.
"""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT_REFERENCE_ALLOWLIST: frozenset[str] = frozenset({
    # Canonical definition site.
    "packages/yoke-core/src/yoke_core/domain/agents_render_workspace.py",
    # Public re-export for back-compat with CLI / legacy consumers — the
    # renderer module surfaces the symbol so ``from agents_render import
    # _repo_root`` keeps working for the CLI fallback. Reader hot paths
    # inside this same module funnel through ``require_reader_root``.
    "packages/yoke-core/src/yoke_core/domain/agents_render.py",
    # The lint companion module names the symbol in its docstring narrative.
    "packages/yoke-core/src/yoke_core/domain/lint_workspace_cwd_match.py",
    # The scan helper itself references the symbol in its patterns.
    "packages/yoke-core/src/yoke_core/domain/lint_workspace_repo_root_scan.py",
    # Lint tests assert the scan shape and intentionally name the symbol.
    "runtime/api/domain/test_lint_workspace_cwd_match.py",
    "runtime/api/domain/test_lint_workspace_repo_root_scan.py",
    # The workspace-anchored fixture's docstring names the prior pattern
    # so future readers know why the helper exists.
    "runtime/api/domain/test_agents_render_workspace_fixtures.py",
})


_REPO_ROOT_REFERENCE_PATTERNS = (
    # ``from yoke_core.domain.agents_render(_workspace)? import _repo_root``
    re.compile(
        r"from\s+(?:runtime\.api\.domain|yoke_core\.domain)"
        r"\.agents_render(?:_workspace)?\s+import\s+"
        r"[^\n]*\b_repo_root\b"
    ),
    # Attribute access: ``agents_render._repo_root(`` /
    # ``agents_render_workspace._repo_root(``.
    re.compile(r"\bagents_render(?:_workspace)?\._repo_root\("),
    # mock.patch on the renderer's re-exported symbol.
    re.compile(
        r"""patch\(\s*["'](?:runtime\.api\.domain|yoke_core\.domain)"""
        r"""\.agents_render(?:_workspace)?"""
        r"""\._repo_root["']"""
    ),
)


_BUILD_OUTPUT_REL = re.compile(r"packages/[^/]+/build/")


def scan_repo_root_references(scan_root: Path) -> list[str]:
    """Flag direct ``_repo_root`` references outside the allowlist.

    Walks live Python source roots under ``scan_root``, skipping every file path that
    appears in :data:`REPO_ROOT_REFERENCE_ALLOWLIST` (paths are POSIX
    relative to ``scan_root``). For every remaining ``*.py`` file the
    scan tests each of the three pattern shapes that name ``_repo_root``
    directly or via ``mock.patch``. Returns one
    ``<rel-path>:<line>: <match>`` string per violation; an empty list
    means the tree is clean.
    """
    violations: list[str] = []
    for source_root in (scan_root / "runtime", scan_root / "packages"):
        if not source_root.is_dir():
            continue
        for py in sorted(source_root.rglob("*.py")):
            rel = py.relative_to(scan_root).as_posix()
            if rel in REPO_ROOT_REFERENCE_ALLOWLIST:
                continue
            if _BUILD_OUTPUT_REL.match(rel):
                # In-tree wheel builds leave gitignored setuptools
                # build/lib source copies; generated output is not
                # live source and must not re-flag allowlisted files.
                continue
            try:
                text = py.read_text(encoding="utf-8")
            except OSError:
                continue
            for pat in _REPO_ROOT_REFERENCE_PATTERNS:
                for match in pat.finditer(text):
                    lineno = text[: match.start()].count("\n") + 1
                    snippet = match.group(0).strip()
                    violations.append(f"{rel}:{lineno}: {snippet}")
    return violations


__all__ = [
    "REPO_ROOT_REFERENCE_ALLOWLIST",
    "scan_repo_root_references",
]
