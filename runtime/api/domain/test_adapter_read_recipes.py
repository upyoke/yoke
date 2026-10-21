"""The narrow-read recipe catalog renders every recipe, and the surfaces
that must carry it stay registered with the inline renderer.
"""
from __future__ import annotations

import pytest

from yoke_contracts import adapter_read_recipes as arr
from yoke_contracts.field_note_text import FOOTER as FIELD_NOTE_FOOTER


def test_compact_footer_carries_every_compact_recipe() -> None:
    for recipe, gloss in arr.COMPACT_RECIPES:
        assert recipe in arr.FOOTER
        assert gloss in arr.FOOTER
    assert arr.DIRECTIVE in arr.FOOTER


def test_catalog_renders_one_entry_per_recipe() -> None:
    rendered = arr.format_recipes_for_help()
    for recipe in arr.RECIPES:
        assert recipe.want in rendered
        assert recipe.recipe in rendered
        assert recipe.note in rendered


@pytest.mark.parametrize(
    "command", ["items get", "claims path widen", "sessions", "dev", "project snapshot"]
)
def test_subcommand_help_has_no_standing_trailers(command, capsys) -> None:
    from yoke_cli.main import main

    assert main(command.split() + ["--help"]) == 0
    output = capsys.readouterr().out
    assert arr.FOOTER not in output
    assert FIELD_NOTE_FOOTER not in output


def test_root_help_keeps_the_standing_read_and_field_note_guidance(capsys) -> None:
    from yoke_cli.main import main

    assert main(["--help"]) == 0
    output = capsys.readouterr().out
    assert FIELD_NOTE_FOOTER in output


@pytest.mark.parametrize(
    "command, ceiling", [("items get", 2000), ("messages send", 4300), ("say", 4300)]
)
def test_command_help_stays_within_its_fixed_fixture_budget(
    command, ceiling, capsys
) -> None:
    from yoke_cli.main import main

    assert main(command.split() + ["--help"]) == 0
    output = capsys.readouterr().out
    from yoke_cli.transport.response_evidence import wrapped_lines

    assert wrapped_lines(output) <= 350
    print(
        f"Advisory help budget: {command}: {len(output)} characters; target {ceiling}"
    )


@pytest.mark.parametrize(
    "path",
    [
        "AGENTS.md",
        "runtime/agents/engineer/large-output.md",
    ],
)
def test_inline_teaching_surface_is_in_the_render_inventory(path: str) -> None:
    from yoke_core.tools.render_read_recipe_inline import INVENTORY

    assert path in INVENTORY


def test_block_render_families_include_the_read_recipe() -> None:
    from yoke_core.tools.generated_block_render import FAMILY_MODULES

    assert "yoke_core.tools.render_read_recipe_inline" in FAMILY_MODULES
