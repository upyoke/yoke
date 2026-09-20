"""The narrow-read recipe contract, and the surfaces that must carry it.

Two things are locked here. The canonical text stays positive — it names
shapes to run and never a shape to avoid, because a teaching surface is
copied by whoever reads it — and every surface an agent consults while
deciding how to invoke a command carries it.
"""

from __future__ import annotations

import argparse
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


def test_every_subcommand_help_carries_both_trailer_stanzas() -> None:
    from yoke_cli.commands._helpers import attach_help_trailer

    parser = argparse.ArgumentParser(prog="yoke example")
    attach_help_trailer(parser)
    assert arr.FOOTER in parser.epilog
    assert FIELD_NOTE_FOOTER in parser.epilog


def test_trailer_attach_is_idempotent() -> None:
    from yoke_cli.commands._helpers import attach_help_trailer

    parser = argparse.ArgumentParser(prog="yoke example")
    attach_help_trailer(parser)
    once = parser.epilog
    attach_help_trailer(parser)
    assert parser.epilog == once


def test_trailer_adds_only_the_missing_stanza() -> None:
    """A parser composing one stanza itself still gains the other."""
    from yoke_cli.commands._helpers import attach_help_trailer

    parser = argparse.ArgumentParser(
        prog="yoke example", description=f"body\n\n{FIELD_NOTE_FOOTER}"
    )
    attach_help_trailer(parser)
    assert arr.FOOTER in parser.epilog
    assert parser.epilog.count(FIELD_NOTE_FOOTER) == 0


def test_startup_packet_points_at_the_help_that_carries_the_recipe() -> None:
    """The startup block is a question-to-command list, not a recipe list.

    Its tightest harness channel is measured in tens of bytes, so the
    narrow read is named there and spelled out in the `--help` the line
    sends the reader to.
    """
    from yoke_core.domain.main_agent_packet import render_main_agent_block

    block = render_main_agent_block()
    assert "narrow reads" in block
    assert "`--help`" in block
    assert arr.FOOTER not in block


def test_launch_sentence_names_the_message_read() -> None:
    from yoke_contracts.session_control.launch_bootstrap import (
        native_launch_bootstrap,
    )

    sentence = native_launch_bootstrap("launch-id")
    assert "yoke messages list --state pending" in sentence
    assert "yoke messages get MESSAGE-ID" in sentence


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
