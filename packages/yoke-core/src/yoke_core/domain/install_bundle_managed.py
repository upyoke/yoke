"""Managed-markdown + permissions layers of the install bundle.

Split out of :mod:`install_bundle` so the bundle renderer stays within its
size budget. Owns the repo-root doctrine source files, the managed-markdown
block set a managed project installs, and the Claude permissions region.

The block bodies are extracted from the server tree's OWN doctrine files —
this repo dogfoods the same managed-block system it installs — so there is one
source for the shipped agnostic doctrine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from yoke_contracts.project_contract.managed_block import extract_block_body
from yoke_core.domain.install_bundle import InstallBundleError, _read_text

# Repo-root FILES (not dirs) every server tree and the packaged snapshot carry
# alongside the source dirs; ``build_bundle`` extracts each file's managed
# block. The snapshot materializer and its drift check keep the wheel copy
# byte-exact with these sources the same way they do for the dirs.
INSTALL_BUNDLE_SOURCE_FILES = ("AGENTS.md", "CODEX.md")

# The managed-markdown doctrine sources and the co-owned files each block
# installs into. ``AGENTS.md`` and its ``CLAUDE.md`` auto-load twin carry the
# shared doctrine; ``CODEX.md`` carries the Codex shell.
_DOCTRINE_SOURCE = "AGENTS.md"
_CODEX_SHELL_SOURCE = "CODEX.md"


def managed_bundle_keys(root: Path) -> Dict[str, Any]:
    """The ``managed_markdown`` + ``claude_settings_permissions`` bundle keys."""
    return {
        "managed_markdown": _managed_markdown(root),
        "claude_settings_permissions": _claude_settings_permissions(),
    }


def _managed_markdown(root: Path) -> Dict[str, Any]:
    """Managed-markdown blocks + install targets for a managed project.

    The doctrine block installs into both ``AGENTS.md`` and its ``CLAUDE.md``
    auto-load twin; the Codex shell installs into ``CODEX.md``.
    """
    return {
        "blocks": {
            "doctrine": _managed_block_body(root / _DOCTRINE_SOURCE),
            "codex_shell": _managed_block_body(root / _CODEX_SHELL_SOURCE),
        },
        "targets": [
            {"path": "AGENTS.md", "block": "doctrine"},
            {"path": "CLAUDE.md", "block": "doctrine"},
            {"path": "CODEX.md", "block": "codex_shell"},
        ],
    }


def _managed_block_body(path: Path) -> str:
    """Extract one doctrine file's managed-block body, or raise."""
    text = _read_text(path)
    if text is None:
        raise InstallBundleError(
            f"managed-markdown doctrine source is missing or non-text: {path}"
        )
    body = extract_block_body(text)
    if not body:
        raise InstallBundleError(
            f"doctrine source carries no Yoke managed block: {path}"
        )
    return body


def _claude_settings_permissions() -> Dict[str, Any]:
    """The permissions region a managed project's .claude/settings.json needs.

    Single source: the Claude substrate renderer's permission contract. Without
    these a fresh project prompts on every Bash/Write/Edit/Monitor call.
    """
    from yoke_core.domain.agents_render_claude import CLAUDE_PERMISSIONS

    return {
        "allow": list(CLAUDE_PERMISSIONS["allow"]),
        "auto_memory_enabled": False,
    }


__all__ = [
    "INSTALL_BUNDLE_SOURCE_FILES",
    "managed_bundle_keys",
]
