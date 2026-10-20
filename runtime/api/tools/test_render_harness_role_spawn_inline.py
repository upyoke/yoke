"""Tests for yoke_core.tools.render_harness_role_spawn_inline."""

from __future__ import annotations

import pathlib

from yoke_core.domain.harness_capability_registry import HARNESS_UNIVERSE
from yoke_core.tools import render_harness_role_spawn_inline as spawn
from yoke_core.tools.generated_block_render import FAMILY_MODULES

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SPAWN_PAGE = REPO_ROOT / ".agents/skills/yoke/shared/role-spawn.md"


def _text(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def test_family_is_registered() -> None:
    assert "yoke_core.tools.render_harness_role_spawn_inline" in FAMILY_MODULES


def test_every_registered_harness_has_a_line() -> None:
    block = spawn.build_block()
    for harness_id in HARNESS_UNIVERSE:
        assert f"- `{harness_id}`: " in block
    assert "yoke-engineer" not in block


def test_rendered_codex_spawn_names_the_custom_agent() -> None:
    page = SPAWN_PAGE.read_text(encoding="utf-8")

    assert spawn.build_block() in page
    assert "- `codex`: `codex agent: .codex/agents/yoke-<role>.toml" in page
    assert "custom agent of that name" in page


def test_conduct_engineer_dispatch_names_its_agent_and_the_spawn_page() -> None:
    text = _text(".agents/skills/yoke/conduct/dispatch-context-prompts.md")

    assert "Spawn `yoke-engineer` ([role spawn](../shared/role-spawn.md))" in text
    assert "DispatchDescriptor" not in text


def test_every_dispatching_skill_points_to_the_spawn_page() -> None:
    for rel_path, agent in (
        (".agents/skills/yoke/conduct/simulation-gate-criteria.md", "yoke-simulator"),
        (".agents/skills/yoke/shared/tester-dispatch-template.md", "yoke-tester"),
    ):
        text = _text(rel_path)
        assert f"Spawn `{agent}` ([role spawn](" in text
        assert "DispatchDescriptor" not in text


def test_check_reports_drift_without_writing(tmp_path: pathlib.Path) -> None:
    rel_path = spawn.INVENTORY[0]
    target = tmp_path / rel_path
    target.parent.mkdir(parents=True)
    stale = (
        "# Doc\n\n<!-- BEGIN GENERATED: harness-role-spawn -->\nold\n"
        "<!-- END GENERATED: harness-role-spawn -->\n"
    )
    target.write_text(stale, encoding="utf-8")

    result = spawn.render(tmp_path, check=True)

    assert [outcome.path for outcome in result.changed] == [rel_path]
    assert target.read_text(encoding="utf-8") == stale
