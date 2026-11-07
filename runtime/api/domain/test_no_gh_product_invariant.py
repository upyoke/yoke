"""Simple guard for the no-host-GitHub-CLI product invariant."""

from __future__ import annotations

import re
import ast
from pathlib import Path


_FORBIDDEN = re.compile(
    "|".join(
        (
            r'\[\s*["\']gh["\']',
            r'shutil\.which\(\s*["\']gh["\']\s*\)',
            r"\bbrew\s+install\s+gh\b",
            r"\bgh\s+(api|issue|pr|repo|run|secret|workflow)\b",
        )
    )
)

_EXCLUDED_PREFIXES = (
    "docs/archive/",
    "docs/archive/legacy-plan-artifacts/",
)

# GitHub-hosted release/profile jobs supply gh; installed product paths must
# never import these source-maintainer scripts.
_CI_TOOLS = {
    "yoke_core.tools.release_tag_validation",
    "yoke_core.tools.publish_server_image",
    "yoke_core.tools.ci_durations_refresh",
}
_CI_TOOL_PATHS = {
    "packages/yoke-core/src/" + name.replace(".", "/") + ".py"
    for name in _CI_TOOLS
}

_SCAN_DIRS = (
    "packages",
    "runtime/api",
    "runtime/harness",
    ".agents/skills/yoke",
    "docs",
    "templates",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _is_excluded(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    if rel == "runtime/api/domain/test_no_gh_product_invariant.py" or rel in _CI_TOOL_PATHS:
        return True
    if any(rel.startswith(prefix) for prefix in _EXCLUDED_PREFIXES):
        return True
    name = path.name
    return name.startswith("test_") or name.endswith("_test.py")


def _iter_targets(root: Path):
    for rel in _SCAN_DIRS:
        base = root / rel
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in (".py", ".md", ".toml"):
                yield path
    for name in ("AGENTS.md", "CLAUDE.md", "CODEX.md"):
        path = root / name
        if path.is_file():
            yield path


# QA fixtures are external test resources; their operator-authored recipes do
# not add a GitHub CLI dependency to the product's GitHub operations.
_FIXTURE_RECIPE_SECTIONS = {
    "docs/public/verification/exploration.md": "## Cleanup",
    "docs/testing-verification/qa-fixture-cleanup.md": "## Delete the test's repositories",
    "runtime/harness/claude/agents/yoke-qa-walker.md": "## Cleanup",
    "runtime/harness/codex/agents/yoke-qa-walker.toml": "## Cleanup",
    "runtime/harness/cursor/agents/yoke-qa-walker.md": "## Cleanup",
}
_FIXTURE_COMMAND = re.compile(
    r"`gh repo (?:create OWNER/NAME --private|delete OWNER/NAME --yes)`"
)


def _has_product_dependency(rel: str, section: str, line: str) -> bool:
    if section == _FIXTURE_RECIPE_SECTIONS.get(rel):
        line = _FIXTURE_COMMAND.sub("", line)
    return bool(_FORBIDDEN.search(line))


def test_fixture_recipes_do_not_allow_other_github_cli_dependencies() -> None:
    rel = "docs/public/verification/exploration.md"
    section = "## Cleanup"
    for command in ("create OWNER/NAME --private", "delete OWNER/NAME --yes"):
        line = f"`gh repo {command}`"
        assert not _has_product_dependency(rel, section, line)
        assert _has_product_dependency(rel, "## Contract", line)
        assert _has_product_dependency("runtime/api/product.py", section, line)
    for line in ("gh pr list", "gh repo delete real/project --yes", "gh repo create OWNER/NAME --public"):
        assert _has_product_dependency(rel, section, line)
    assert _has_product_dependency(rel, section, "`gh repo delete OWNER/NAME --yes`; gh api /user")


def test_no_host_gh_cli_dependency_in_live_surfaces() -> None:
    root = _repo_root()
    violations: list[str] = []
    for path in _iter_targets(root):
        if _is_excluded(path, root):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        section = ""
        rel = path.relative_to(root).as_posix()
        for line_no, line in enumerate(text.splitlines(), start=1):
            if line.startswith("## "):
                section = line
            if _has_product_dependency(rel, section, line):
                violations.append(f"{rel}:{line_no}: {line.strip()}")

    assert not violations, (
        "Host GitHub CLI dependency residue found in live Yoke surfaces. "
        "Use bearer-token REST through project GitHub auth instead.\n\n"
        + "\n".join(violations[:40])
    )


def test_ci_github_tools_are_not_imported_by_product_modules() -> None:
    root = _repo_root()
    violations = []
    for package in (root / "packages").iterdir():
        for path in (package / "src").rglob("*.py"):
            if path.relative_to(root).as_posix() in _CI_TOOL_PATHS:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    imported = {alias.name for alias in node.names}
                elif isinstance(node, ast.ImportFrom):
                    imported = {node.module} | {
                        f"{node.module}.{alias.name}" for alias in node.names
                    }
                else:
                    continue
                if imported & _CI_TOOLS:
                    violations.append(str(path.relative_to(root)))
    assert not violations, f"CI-only GitHub tools imported by product: {violations}"
