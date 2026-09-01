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
from typing import Any, Dict, List

from yoke_contracts.project_contract.managed_block import extract_block_body
from yoke_core.domain.install_bundle import (
    DOCS_SOURCE,
    InstallBundleError,
    _read_text,
)

# Repo-root FILES (not dirs) every server tree and the packaged snapshot carry
# alongside the source dirs; ``build_bundle`` extracts each file's managed
# block. The snapshot materializer keeps the wheel copy byte-exact with each
# file's project-agnostic managed region while leaving repo-only tails local.
INSTALL_BUNDLE_SOURCE_FILES = ("AGENTS.md", "CODEX.md", "CURSOR.md")

# The managed-markdown doctrine sources and the co-owned files each block
# installs into. ``AGENTS.md`` and its ``CLAUDE.md`` auto-load twin carry the
# shared doctrine; ``CODEX.md`` and ``CURSOR.md`` carry the harness shells.
_DOCTRINE_SOURCE = "AGENTS.md"
_CODEX_SHELL_SOURCE = "CODEX.md"
_CURSOR_SHELL_SOURCE = "CURSOR.md"


def managed_bundle_keys(root: Path) -> Dict[str, Any]:
    """The managed-markdown and managed ``.claude/settings.json`` regions."""
    return {
        "managed_markdown": _managed_markdown(root),
        "claude_settings_permissions": _claude_settings_permissions(),
        "claude_settings_status_line": _claude_settings_status_line(),
    }


def _managed_markdown(root: Path) -> Dict[str, Any]:
    """Managed-markdown blocks + install targets for a managed project.

    The doctrine block installs into both ``AGENTS.md`` and its ``CLAUDE.md``
    auto-load twin; the Codex and Cursor shells install into their own files.
    """
    return {
        "blocks": {
            "doctrine": _doctrine_block(root),
            "codex_shell": _managed_block_body(root / _CODEX_SHELL_SOURCE),
            "cursor_shell": _managed_block_body(root / _CURSOR_SHELL_SOURCE),
        },
        "targets": [
            {"path": "AGENTS.md", "block": "doctrine"},
            {"path": "CLAUDE.md", "block": "doctrine"},
            {"path": "CODEX.md", "block": "codex_shell"},
            {"path": "CURSOR.md", "block": "cursor_shell"},
        ],
    }


def _doctrine_block(root: Path) -> str:
    """The project-agnostic authored doctrine body.

    Generated schema/API context belongs to session orientation, not this
    auto-loaded file, so project-owned additions retain ample harness headroom.
    """
    return _managed_block_body(root / _DOCTRINE_SOURCE)


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


def docs_bundle_files(root: Path) -> List[Dict[str, str]]:
    """The universal Yoke docs, shipped as yoke-authoritative ``files`` entries.

    Authored under ``docs/public/`` (``DOCS_SOURCE``); installed projects
    receive them at ``.yoke/docs/`` (``DOCS_DEST``) so skills/agents that
    cite ``.yoke/docs/...`` resolve. Overwrite-on-refresh and prune like
    every other authored bundle file.
    """
    from yoke_core.domain.install_bundle import (
        DOCS_DEST,
        is_bundle_junk_path,
    )

    source = root / DOCS_SOURCE
    if not source.is_dir():
        raise InstallBundleError(
            f"docs source dir is missing from the server tree: {source}"
        )
    entries: List[Dict[str, str]] = []
    for path in sorted(
        p for p in source.rglob("*") if p.is_file() and not is_bundle_junk_path(p)
    ):
        content = _read_text(path)
        if content is None:
            raise InstallBundleError(f"docs source is missing or non-text: {path}")
        rel = path.relative_to(source).as_posix()
        entries.append({"path": f"{DOCS_DEST}/{rel}", "content": content})
    return entries


def _claude_settings_permissions() -> Dict[str, Any]:
    """The permissions region a managed project's .claude/settings.json needs.

    Single source: the Claude substrate renderer's permission contract. Without
    these a fresh project prompts on every Bash/Edit/Monitor call.
    """
    from yoke_core.domain.agents_render_claude import CLAUDE_PERMISSIONS

    return {
        "allow": list(CLAUDE_PERMISSIONS["allow"]),
        "auto_memory_enabled": False,
    }


def _claude_settings_status_line() -> Dict[str, Any]:
    """The status line an installed project needs to attest served context.

    Single source: the Claude substrate renderer, so the command a customer
    project runs and the one this repo runs cannot drift.
    """
    from yoke_core.domain.agents_render_claude import CLAUDE_STATUS_LINE

    return dict(CLAUDE_STATUS_LINE)


__all__ = [
    "INSTALL_BUNDLE_SOURCE_FILES",
    "managed_bundle_keys",
]
