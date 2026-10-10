"""The narrow-read recipe contract, and the surfaces that must carry it.

Two things are locked here. The canonical text stays positive — it names
shapes to run and never a shape to avoid, because a teaching surface is
copied by whoever reads it — and every surface an agent consults while
deciding how to invoke a command carries it.
"""

from __future__ import annotations

import re

import pytest

from yoke_contracts import adapter_read_recipes as arr
from yoke_contracts.field_note_text import FOOTER as FIELD_NOTE_FOOTER


#: Shapes that would teach the reflex the recipe exists to replace. A
#: teaching surface naming one of these has enshrined the thing the
#: denial message is for. Matched on word boundaries so an ordinary word
#: containing one of them ("whenever") is not a hit.
_ANTI_PATTERN_PATTERNS = (
    r"\|\s*head\b",
    r"\|\s*tail\b",
    r"\bnever\b",
    r"\bdo not pipe\b",
    r"\binstead of slicing\b",
)


def _teaching_text() -> str:
    return "\n".join(
        [
            arr.DIRECTIVE,
            arr.FOOTER,
            arr.format_recipes_for_help(),
        ]
    )


def test_canonical_text_names_only_shapes_to_run() -> None:
    text = _teaching_text()
    for pattern in _ANTI_PATTERN_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        assert match is None, (
            f"teaching text names an anti-pattern {pattern!r}: {match.group(0)!r}"
        )


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


def test_catalog_covers_the_routine_wants() -> None:
    """Each thing the denial telemetry showed callers reaching for."""
    shapes = " ".join(recipe.recipe for recipe in arr.RECIPES)
    assert "yoke items get" in shapes
    assert "yoke messages list" in shapes
    assert "yoke db read" in shapes
    assert "--full" in shapes


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
    assert arr.format_recipes_for_help() in output
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
    assert len(output) <= ceiling
    if command in ("messages send", "say"):
        assert ".yoke/docs/items-and-sessions.md" in output


def test_startup_packet_points_at_the_help_that_carries_the_recipe() -> None:
    """The startup block is a question-to-command list, not a recipe list.

    Its smallest harness channel is measured in tens of bytes, so the
    narrow read is named there and spelled out in the `--help` the line
    sends the reader to.
    """
    from yoke_core.domain.main_agent_packet import render_main_agent_block

    block = render_main_agent_block()
    assert "yoke packets render --role main_agent --topic T" in block
    assert "`--help`" in block
    assert arr.FOOTER not in block


def test_launch_sentence_names_the_message_read() -> None:
    from yoke_contracts.session_control.launch_bootstrap import (
        native_launch_bootstrap,
    )

    sentence = native_launch_bootstrap("launch-id")
    assert "yoke sessions identity --json" in sentence
    assert "yoke session-control launch get launch-id --json" in sentence
    assert "yoke messages get MESSAGE-ID" in sentence
    assert "yoke messages acknowledge MESSAGE-ID" in sentence
    assert "absent from `yoke messages list --state pending`" in sentence


@pytest.mark.parametrize(
    "path",
    [
        "AGENTS.md",
        "docs/public/reference/agent-rules/code-and-cli.md",
        "runtime/agents/engineer/large-output.md",
    ],
)
def test_inline_teaching_surface_is_in_the_render_inventory(path: str) -> None:
    from yoke_core.tools.render_read_recipe_inline import INVENTORY

    assert path in INVENTORY


def test_block_render_families_include_the_read_recipe() -> None:
    from yoke_core.tools.generated_block_render import FAMILY_MODULES

    assert "yoke_core.tools.render_read_recipe_inline" in FAMILY_MODULES
