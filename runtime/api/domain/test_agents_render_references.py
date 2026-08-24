"""Tests for portable, materialized canonical-agent references."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_contracts.session_control.teaching import SUBAGENT_FLEET_GUIDANCE
from yoke_core.domain.agents_render import (
    AGENTS,
    CANONICAL_DIR,
    CLAUDE_OUT_DIR,
    CODEX_OUT_DIR,
    CURSOR_OUT_DIR,
)
from yoke_core.domain.agents_render_conditional import CLAUDE_HARNESS_ID
from yoke_core.domain.agents_render_references import (
    SUBAGENT_FLEET_GUIDANCE_MARKER,
    conditional_reference_paths,
    reference_output_path,
    render_reference_text,
)
from runtime.api.domain.test_agents_render_workspace_fixtures import (
    resolve_live_repo_root,
)


@pytest.fixture
def repo_root() -> Path:
    """Return the checkout containing the rendered agent surfaces."""
    return resolve_live_repo_root()


def test_conditional_references_are_materialized_for_install(
    repo_root: Path,
) -> None:
    """Each on-demand source fragment has a portable Claude reference file."""
    canonical_dir = repo_root / CANONICAL_DIR
    sources = conditional_reference_paths(canonical_dir)
    assert sources, "expected conditional canonical-agent references"

    for source_path in sources:
        output_path = repo_root / reference_output_path(source_path, canonical_dir)
        expected = render_reference_text(
            source_path.read_text(encoding="utf-8"),
            canonical_dir=canonical_dir,
            harness_id=CLAUDE_HARNESS_ID,
        )
        assert output_path.is_file(), f"missing materialized reference: {output_path}"
        assert output_path.read_text(encoding="utf-8") == expected
        assert "runtime/agents/" not in expected, (
            f"{source_path.name} retained a canonical source path"
        )


def test_future_role_fragment_defaults_to_a_materialized_reference(
    tmp_path: Path,
) -> None:
    """New role fragments follow the on-demand reference policy by default."""
    canonical_dir = tmp_path / CANONICAL_DIR
    fragment = canonical_dir / "engineer" / "future-guide.md"
    fragment.parent.mkdir(parents=True)
    fragment.write_text("# Future guidance\n", encoding="utf-8")

    assert conditional_reference_paths(canonical_dir) == (fragment,)
    assert reference_output_path(fragment, canonical_dir).as_posix() == (
        "runtime/harness/claude/agents/references/engineer/future-guide.md"
    )


def test_rendered_adapters_do_not_reference_canonical_source_tree(
    repo_root: Path,
) -> None:
    """Installed harness adapters refer only to installed reference material."""
    adapter_paths = [
        repo_root / CLAUDE_OUT_DIR / f"yoke-{agent}.md" for agent in AGENTS
    ]
    adapter_paths.extend(
        repo_root / CODEX_OUT_DIR / f"yoke-{agent}.toml" for agent in AGENTS
    )
    adapter_paths.extend(
        repo_root / CURSOR_OUT_DIR / f"yoke-{agent}.md" for agent in AGENTS
    )

    for path in adapter_paths:
        text = path.read_text(encoding="utf-8")
        assert "runtime/agents/" not in text, (
            f"{path.relative_to(repo_root)} names the source-only agent tree"
        )


@pytest.mark.parametrize("role", ("product-manager", "product-designer"))
def test_non_bash_agents_receive_read_only_fleet_guidance(
    repo_root: Path,
    role: str,
) -> None:
    canonical = (repo_root / CANONICAL_DIR / f"{role}.md").read_text(encoding="utf-8")
    assert canonical.count(SUBAGENT_FLEET_GUIDANCE_MARKER) == 1

    adapters = (
        repo_root / CLAUDE_OUT_DIR / f"yoke-{role}.md",
        repo_root / CODEX_OUT_DIR / f"yoke-{role}.toml",
        repo_root / CURSOR_OUT_DIR / f"yoke-{role}.md",
    )
    for path in adapters:
        rendered = path.read_text(encoding="utf-8")
        assert SUBAGENT_FLEET_GUIDANCE in rendered
        assert SUBAGENT_FLEET_GUIDANCE_MARKER not in rendered
        assert "yoke say --session" not in rendered
        assert "yoke messages acknowledge" not in rendered


def test_every_harness_subagent_keeps_fleet_receipts_read_only(repo_root: Path) -> None:
    for role in AGENTS:
        adapters = (
            repo_root / CLAUDE_OUT_DIR / f"yoke-{role}.md",
            repo_root / CODEX_OUT_DIR / f"yoke-{role}.toml",
            repo_root / CURSOR_OUT_DIR / f"yoke-{role}.md",
        )
        for path in adapters:
            rendered = path.read_text(encoding="utf-8")
            assert SUBAGENT_FLEET_GUIDANCE in rendered
            assert "never execute a receipt command visible" in rendered
            assert "Top-level receipt action" not in rendered
