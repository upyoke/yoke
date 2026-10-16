"""Rendered agent adapters use current schema and API terms."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import schema_api_context_seed as seed
from runtime.api.domain.test_agents_render_workspace_fixtures import (
    resolve_live_repo_root,
)


_BASH_CAPABLE = ("architect", "engineer", "tester", "simulator", "boss")


@pytest.fixture
def repo_root() -> Path:
    """Workspace-anchored live Yoke checkout root for stale-term scans."""
    return resolve_live_repo_root()


def test_rendered_codex_adapters_have_no_stale_terms(repo_root: Path) -> None:
    """Rendered Codex .toml adapters must not contain the stale
    schema/API names listed in seed.STALE_TERMS. Pairs with the existing
    Claude-side scan in ``test_agents_render_context.py``."""

    codex_dir = repo_root / "runtime/harness/codex/agents"
    for role in _BASH_CAPABLE:
        path = codex_dir / f"yoke-{role}.toml"
        text = path.read_text(encoding="utf-8")
        for stale in seed.STALE_TERMS:
            assert stale not in text, (
                f"yoke-{role}.toml contains stale term {stale!r}"
            )
