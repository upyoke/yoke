"""The user-writing rules have one source and every copy is rendered from it."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.user_writing_rules import RULES
from yoke_core.tools import render_user_writing_inline as family
from yoke_core.tools.generated_block_render import FAMILY_MODULES

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_family_is_checked_with_every_other_family() -> None:
    assert "yoke_core.tools.render_user_writing_inline" in FAMILY_MODULES


def test_inventory_names_the_project_and_global_surfaces() -> None:
    assert family.INVENTORY == (
        "AGENTS.md",
        "packages/yoke-contracts/src/yoke_contracts/global_skill/SKILL.md",
    )


def test_checked_in_surfaces_carry_the_current_rules() -> None:
    result = family.render(REPO_ROOT, check=True)

    assert result.ok and not result.changed
    for rel in family.INVENTORY:
        assert RULES in (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_render_replaces_stale_text(tmp_path: Path) -> None:
    for rel in family.INVENTORY:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"# Rules\n{family.BEGIN_MARKER}\nold rules\n{family.END_MARKER}\n",
            encoding="utf-8",
        )

    assert family.render(tmp_path, check=True).changed
    family.render(tmp_path)

    for rel in family.INVENTORY:
        text = (tmp_path / rel).read_text(encoding="utf-8")
        assert "old rules" not in text and RULES in text
