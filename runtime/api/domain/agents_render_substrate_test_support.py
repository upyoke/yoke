# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

from unittest.mock import patch

import pytest

from yoke_core.domain.agents_render import (
    AGENTS,
    CANONICAL_DIR,
    CODEX_NATIVE_AGENTS_DIR,
    CODEX_OUT_DIR,
    ROLES_WITH_INLINE_REFERENCES,
    detect_substrate_drift,
    write_all,
)

from yoke_core.domain.agents_render_references import inline_fragment_paths

from yoke_core.domain.agents_render_claude import (
    render_claude_manifest_json,
    render_claude_settings_json,
)

from yoke_core.domain.agents_render_codex import (
    render_codex_agent_body,
    render_codex_hooks_json,
    render_codex_manifest_json,
)


def _seed_minimal_canonical_tree(repo: Path) -> None:
    canonical = repo / CANONICAL_DIR
    canonical.mkdir(parents=True)
    claude_spec = '{"name": "yoke-architect", "description": "x", "tools": "Read"}'
    codex_spec = '{"name": "yoke-architect", "description": "x"}'
    cursor_spec = '{"name": "yoke-architect", "description": "x"}'
    (canonical / "architect.md").write_text("# canonical body\n", encoding="utf-8")
    (canonical / "architect.claude.json").write_text(claude_spec)
    (canonical / "architect.codex.json").write_text(codex_spec)
    (canonical / "architect.cursor.json").write_text(cursor_spec)
