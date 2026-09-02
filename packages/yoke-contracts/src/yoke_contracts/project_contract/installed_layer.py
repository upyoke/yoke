"""Tracked provenance for a project's installed Yoke operating layer.

The project install manifest is machine-local and therefore absent from
clones and linked worktrees.  This small tracked receipt travels with the
project checkout alongside the copied skills so every checkout can identify
the engine release that authored its teaching.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from yoke_contracts.project_contract.install_manifest import INSTALL_MANIFEST_REL


INSTALLED_LAYER_RECEIPT_REL = ".yoke-operating-layer.json"
INSTALLED_LAYER_RECEIPT_SCHEMA = 1
SOURCE_ENGINE_RELEASE_KEY = "source_engine_release"
SOURCE_BUILD_KEY = "source_build"

# Where the layer lands inside a project checkout: the destinations the
# install bundle renders into, and the paths a pre-install checkout inspection
# reports (and on request removes) when a repository already carries a layer.
# Both surfaces read them here, because a destination the installer writes and
# the inspection does not know about is residue nothing can see.
CANONICAL_SKILLS_DEST = ".agents/skills/yoke"
CLAUDE_SKILLS_DEST = ".claude/skills/yoke"
CODEX_SKILLS_DEST = ".codex/skills/yoke"
CURSOR_SKILLS_DEST = ".cursor/skills/yoke"
CLAUDE_AGENTS_DEST = ".claude/agents"
CODEX_AGENTS_DEST = ".codex/agents"
CURSOR_AGENTS_DEST = ".cursor/agents"
CLAUDE_RULES_DEST = ".claude/rules"
PROJECT_CONTRACT_DEST = ".yoke"

# Directories the layer owns outright: everything under them arrived with a
# Yoke install, so a scan counts the whole subtree and a removal takes it.
INSTALLED_LAYER_DIR_RELS: tuple[str, ...] = (
    PROJECT_CONTRACT_DEST,
    CANONICAL_SKILLS_DEST,
    CLAUDE_SKILLS_DEST,
    CODEX_SKILLS_DEST,
    CURSOR_SKILLS_DEST,
    CLAUDE_RULES_DEST,
)
# Directories the layer shares with the harness: only the ``yoke-`` adapters
# inside them belong to Yoke.
INSTALLED_LAYER_AGENT_DIR_RELS: tuple[str, ...] = (
    CLAUDE_AGENTS_DEST,
    CODEX_AGENTS_DEST,
    CURSOR_AGENTS_DEST,
)
INSTALLED_LAYER_AGENT_PREFIX = "yoke-"
# Files the layer owns on their own, outside any layer directory.
INSTALLED_LAYER_FILE_RELS: tuple[str, ...] = (INSTALLED_LAYER_RECEIPT_REL,)
# Files a project co-owns, where the layer occupies a marked region: the
# managed Markdown block and the merged harness hook entries.
INSTALLED_LAYER_MARKDOWN_RELS: tuple[str, ...] = (
    "AGENTS.md",
    "CLAUDE.md",
    "CODEX.md",
    "CURSOR.md",
)
INSTALLED_LAYER_HOOK_RELS: tuple[str, ...] = (
    ".claude/settings.json",
    ".codex/hooks.json",
    ".cursor/hooks.json",
)
# Every hook entry the installer merges runs the same entrypoint, whatever
# shell preamble the harness needs around it, so its presence in a command
# identifies the entry as Yoke's without a machine-local install manifest —
# which a fresh clone never has.
INSTALLED_LAYER_HOOK_COMMAND_TOKEN = "yoke hook evaluate"


@dataclass(frozen=True)
class InstalledLayerReceipt:
    """Validated installed-layer release identity and its owning checkout."""

    project_root: Path
    source_engine_release: str
    source_build: str = ""


def render_installed_layer_receipt(
    source_engine_release: str,
    *,
    source_build: str = "",
) -> str:
    """Return deterministic receipt JSON for one engine release."""
    release = str(source_engine_release or "").strip()
    if not release:
        raise ValueError("installed-layer source engine release is empty")
    payload = {
        "schema": INSTALLED_LAYER_RECEIPT_SCHEMA,
        SOURCE_ENGINE_RELEASE_KEY: release,
    }
    build = str(source_build or "").strip()
    if build:
        payload[SOURCE_BUILD_KEY] = build
    return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"


def installed_layer_receipt_entry(
    source_engine_release: str,
    *,
    source_build: str = "",
) -> Dict[str, str]:
    """Install-bundle file entry carrying the layer's release provenance."""
    return {
        "path": INSTALLED_LAYER_RECEIPT_REL,
        "content": render_installed_layer_receipt(
            source_engine_release,
            source_build=source_build,
        ),
    }


def _validated_receipt(
    payload: object,
    project_root: Path,
) -> Optional[InstalledLayerReceipt]:
    if not isinstance(payload, dict):
        return None
    schema = payload.get("schema")
    release = payload.get(SOURCE_ENGINE_RELEASE_KEY)
    build = payload.get(SOURCE_BUILD_KEY, "")
    if not (
        isinstance(schema, int)
        and not isinstance(schema, bool)
        and schema == INSTALLED_LAYER_RECEIPT_SCHEMA
        and isinstance(release, str)
        and release.strip()
        and isinstance(build, str)
    ):
        return None
    return InstalledLayerReceipt(project_root, release.strip(), build.strip())


def _legacy_manifest_receipt(
    project_root: Path,
) -> Optional[InstalledLayerReceipt]:
    """Recover provenance written by installs predating tracked receipts."""
    path = project_root / INSTALL_MANIFEST_REL
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    release = payload.get("yoke_version")
    if not isinstance(release, str) or not release.strip():
        return None
    return InstalledLayerReceipt(project_root, release.strip())


def read_installed_layer_receipt(start: Path) -> Optional[InstalledLayerReceipt]:
    """Read provenance inside the nearest project boundary, failing silent."""
    try:
        current = start.expanduser().resolve()
    except (OSError, RuntimeError):
        return None
    if current.is_file():
        current = current.parent
    for project_root in (current, *current.parents):
        path = project_root / INSTALLED_LAYER_RECEIPT_REL
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, ValueError):
                return None
            return _validated_receipt(payload, project_root)
        manifest = project_root / INSTALL_MANIFEST_REL
        if manifest.exists():
            return _legacy_manifest_receipt(project_root)
        if (
            (project_root / ".yoke").is_dir()
            or (project_root / ".git").exists()
        ):
            return None
    return None


__all__ = [
    "CANONICAL_SKILLS_DEST",
    "CLAUDE_AGENTS_DEST",
    "CLAUDE_RULES_DEST",
    "CLAUDE_SKILLS_DEST",
    "CODEX_AGENTS_DEST",
    "CODEX_SKILLS_DEST",
    "CURSOR_AGENTS_DEST",
    "CURSOR_SKILLS_DEST",
    "INSTALLED_LAYER_AGENT_DIR_RELS",
    "INSTALLED_LAYER_AGENT_PREFIX",
    "INSTALLED_LAYER_DIR_RELS",
    "INSTALLED_LAYER_FILE_RELS",
    "INSTALLED_LAYER_HOOK_COMMAND_TOKEN",
    "INSTALLED_LAYER_HOOK_RELS",
    "INSTALLED_LAYER_MARKDOWN_RELS",
    "INSTALLED_LAYER_RECEIPT_REL",
    "INSTALLED_LAYER_RECEIPT_SCHEMA",
    "PROJECT_CONTRACT_DEST",
    "InstalledLayerReceipt",
    "SOURCE_ENGINE_RELEASE_KEY",
    "SOURCE_BUILD_KEY",
    "installed_layer_receipt_entry",
    "read_installed_layer_receipt",
    "render_installed_layer_receipt",
]
