"""Shared fake-bundle builders for the project-install test files.

Filename omits the ``test_`` prefix so pytest does not collect it. The
fake bundle mirrors the frozen install-bundle contract shape without any
network or DB dependency.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from yoke_core.domain.project_contract import (
    CATEGORY_PROJECT_POLICY,
    SEED_IF_MISSING,
)
from yoke_core.domain.project_install_strategy import STRATEGY_INSTALL_POLICY
from yoke_core.domain.strategy_docs_header import render_file_text
from yoke_core.domain.strategy_docs_paths import strategy_view_rel_path

CLAUDE_PRE_CMD = "/bin/zsh -lc 'yoke hook evaluate PreToolUse'"
CLAUDE_STOP_CMD = "/bin/zsh -lc 'yoke hook evaluate Stop'"
CODEX_PRE_CMD = (
    "/bin/zsh -lc 'env YOKE_EXECUTOR=codex YOKE_PROVIDER=openai "
    "yoke hook evaluate PreToolUse'"
)

DEFAULT_FILES = [
    {"path": ".claude/skills/yoke/SKILL.md", "content": "# yoke\n"},
    {"path": ".codex/skills/yoke/SKILL.md", "content": "# yoke\n"},
    {
        "path": ".claude/skills/yoke/onboard-project/SKILL.md",
        "content": "# onboard-project\n",
    },
    {
        "path": ".codex/skills/yoke/onboard-project/SKILL.md",
        "content": "# onboard-project\n",
    },
]

# Sentinels: build a bundle WITHOUT the project_contract_files /
# strategy_files keys (the shapes pre-contract / pre-strategy servers emit).
OMIT_CONTRACT = object()
OMIT_STRATEGY = object()


def contract_entry(path: str, content: str) -> Dict[str, str]:
    return {
        "path": path,
        "content": content,
        "install_policy": SEED_IF_MISSING,
        "category": CATEGORY_PROJECT_POLICY,
    }


def strategy_entry(
    slug: str, body: str, updated_at: str = "2026-06-10T00:00:00Z",
) -> Dict[str, str]:
    """One db-render strategy bundle entry with a real CAS header."""
    return {
        "path": strategy_view_rel_path(slug),
        "content": render_file_text(slug, updated_at, body),
        "install_policy": STRATEGY_INSTALL_POLICY,
    }


DEFAULT_CONTRACT_FILES = [
    contract_entry(".yoke/lint-config", "lint_main_commit=deny\n"),
    contract_entry(".yoke/board.json", "{}\n"),
    contract_entry(".yoke/board-art", "## Master Map\n"),
    contract_entry(".yoke/runbooks/deploy.md", "# Deploy\n"),
]


def entry(command: str, matcher: Optional[str] = None) -> Dict[str, Any]:
    built: Dict[str, Any] = {"hooks": [{"type": "command", "command": command}]}
    if matcher is not None:
        built["matcher"] = matcher
    return built


def claude_hooks() -> Dict[str, Any]:
    return {
        "PreToolUse": [
            entry(CLAUDE_PRE_CMD, "Bash"),
            entry(CLAUDE_PRE_CMD, "Edit"),
        ],
        "Stop": [entry(CLAUDE_STOP_CMD)],
    }


def codex_hooks() -> Dict[str, Any]:
    return {"PreToolUse": [entry(CODEX_PRE_CMD, "Bash")]}


def make_bundle(
    files: Optional[List[Dict[str, str]]] = None,
    *,
    bundle_schema: int = 1,
    claude: Optional[Dict[str, Any]] = None,
    codex: Optional[Dict[str, Any]] = None,
    contract: Any = None,
    strategy: Any = None,
) -> Dict[str, Any]:
    """Fake bundle; ``contract=OMIT_CONTRACT`` / ``strategy=OMIT_STRATEGY``
    drop the matching key entirely (pre-feature server shapes)."""
    bundle = {
        "bundle_schema": bundle_schema,
        "yoke_version": "9.9.9",
        "project_id": 7,
        "project_slug": "demo",
        "files": DEFAULT_FILES if files is None else files,
        "project_contract_files": (
            DEFAULT_CONTRACT_FILES if contract is None else contract
        ),
        "strategy_files": [] if strategy is None else strategy,
        "hooks": {
            "claude_settings_hooks": claude_hooks() if claude is None else claude,
            "codex_hooks": codex_hooks() if codex is None else codex,
        },
    }
    if contract is OMIT_CONTRACT:
        del bundle["project_contract_files"]
    if strategy is OMIT_STRATEGY:
        del bundle["strategy_files"]
    return bundle


__all__ = [
    "CLAUDE_PRE_CMD",
    "CLAUDE_STOP_CMD",
    "CODEX_PRE_CMD",
    "DEFAULT_CONTRACT_FILES",
    "DEFAULT_FILES",
    "OMIT_CONTRACT",
    "OMIT_STRATEGY",
    "claude_hooks",
    "codex_hooks",
    "contract_entry",
    "entry",
    "make_bundle",
    "strategy_entry",
]
