"""Simple guard for the no-host-GitHub-CLI product invariant."""

from __future__ import annotations

import re
from pathlib import Path


_FORBIDDEN = re.compile(
    "|".join(
        (
            r'\[\s*["\']gh["\']',
            r'shutil\.which\(\s*["\']gh["\']\s*\)',
            r"\bbrew\s+install\s+gh\b",
            r"\bgh\s+(api|issue|pr|run|secret)\b",
        )
    )
)

_EXCLUDED_PREFIXES = (
    "docs/archive/",
    "docs/archive/legacy-plan-artifacts/",
)

_SCAN_DIRS = (
    "runtime/api",
    "runtime/harness",
    ".agents/skills/yoke",
    "docs",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _is_excluded(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    if rel == "runtime/api/domain/test_no_gh_product_invariant.py":
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


def test_no_host_gh_cli_dependency_in_live_surfaces() -> None:
    root = _repo_root()
    violations: list[str] = []
    for path in _iter_targets(root):
        if _is_excluded(path, root):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if _FORBIDDEN.search(line):
                rel = path.relative_to(root).as_posix()
                violations.append(f"{rel}:{line_no}: {line.strip()}")

    assert not violations, (
        "Host GitHub CLI dependency residue found in live Yoke surfaces. "
        "Use PAT-backed REST through project GitHub auth instead.\n\n"
        + "\n".join(violations[:40])
    )
