"""No teaching surface leaves ``--impacted main`` without a bound or widen."""

from __future__ import annotations

import re
from pathlib import Path

from runtime.api.skill_doc_regressions_test_helpers import REPO, _read

_BARE_IMPACTED_MAIN = re.compile(
    r"--impacted[ \t]+main(?![ \t\n\\]*--(?:bounded|widen))"
)
_SKIP_DIR_NAMES = {
    ".git",
    ".worktrees",
    "__pycache__",
    "archive",
    "node_modules",
}
_TEXT_SUFFIXES = {".md", ".py", ".toml", ".txt"}
_ROOT_DOCS = (
    "AGENTS.md",
    "CLAUDE.md",
    "CODEX.md",
    "CONTRIBUTING.md",
    "CURSOR.md",
)
_SURFACE_ROOTS = (
    REPO / ".agents" / "skills",
    REPO / "docs",
    REPO / "runtime" / "agents",
    REPO / "runtime" / "harness",
    REPO / "packages" / "yoke-core" / "src" / "yoke_core" / "install_bundle_tree",
)


def _is_test_path(path: Path) -> bool:
    name = path.name
    return name.startswith("test_") or name.endswith("_test.py")


def _iter_surface_files() -> list[Path]:
    found: list[Path] = []
    for root_name in _ROOT_DOCS:
        candidate = REPO / root_name
        if candidate.is_file() or candidate.is_symlink():
            found.append(candidate)
    packet = (
        REPO
        / "packages"
        / "yoke-core"
        / "src"
        / "yoke_core"
        / "domain"
        / "schema_api_context_commands_watchers.py"
    )
    found.append(packet)
    for root in _SURFACE_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in _SKIP_DIR_NAMES for part in path.parts):
                continue
            if _is_test_path(path):
                continue
            if path.suffix not in _TEXT_SUFFIXES:
                continue
            found.append(path)
    return found


def test_no_teaching_surface_uses_bare_impacted_main() -> None:
    offenders: list[str] = []
    for path in _iter_surface_files():
        text = _read(path)
        if _BARE_IMPACTED_MAIN.search(text):
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == []
