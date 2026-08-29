"""The selector help says which flags widen the audience and which narrow it.

Every recipient flag once rendered as one flat options block, so nothing
a reader saw distinguished the group that unions from the group that
intersects. Read that way, ``--process K --project P`` looks like a
process holder scoped to a project; it is the whole project roster, and
a report meant for one seat reaches everyone.
"""

from __future__ import annotations

import argparse
import re

import pytest

from yoke_cli.commands.adapters.session_control_common import (
    SELECTOR_ARGUMENTS,
    add_selector_arguments,
)
from yoke_contracts.session_control.teaching import FLEET_ADDRESSING_GUIDANCE

#: Flags that ADD recipients. Every one of these widens the audience.
ANCHOR_FLAGS = ("--item", "--epic-task", "--process", "--project", "--session")
#: Flags that narrow whatever the anchors selected.
FILTER_FLAGS = (
    "--executor",
    "--surface",
    "--role",
    "--execution-lane",
    "--worktree",
    "--machine",
    "--liveness",
    "--exclude-session",
)


def _described_flags() -> dict[str, str]:
    """Map each flag to its own description block.

    Two things defeat a plain substring search. argparse repeats every
    flag in the generated usage line, which carries no help text; and a
    fixed-width window around a flag runs into the next flag's block, so
    the last anchor inherits the first filter's wording. Splitting the
    options section on its entry boundaries gives each flag exactly its
    own text.
    """
    parser = argparse.ArgumentParser(prog="yoke say")
    add_selector_arguments(parser)
    _, separator, options = parser.format_help().partition("options:")
    assert separator, "argparse no longer renders an options section"

    blocks: dict[str, str] = {}
    current: str | None = None
    for line in options.splitlines():
        entry = re.match(r"^  (-{1,2}[\w-]+)", line)
        if entry:
            current = entry.group(1)
            blocks[current] = line
        elif current and line.strip():
            blocks[current] += " " + line.strip()
    return blocks


def _block(flag: str) -> str:
    blocks = _described_flags()
    assert flag in blocks, f"{flag} missing from the selector help"
    return blocks[flag]


def test_every_anchor_flag_is_labelled_an_anchor() -> None:
    for flag in ANCHOR_FLAGS + ("--universe",):
        assert "ANCHOR (union)" in _block(flag), flag


def test_every_filter_flag_is_labelled_a_filter() -> None:
    for flag in FILTER_FLAGS:
        assert "FILTER." in _block(flag), flag


def test_project_says_outright_that_it_widens() -> None:
    assert "WIDENS" in _block("--project")


def test_the_addressing_rule_leads_with_union_versus_intersect() -> None:
    assert FLEET_ADDRESSING_GUIDANCE.startswith("Anchors union, filters intersect.")
    assert "--process K --project P" in FLEET_ADDRESSING_GUIDANCE
    assert "read the recipient count" in FLEET_ADDRESSING_GUIDANCE


def test_the_item_anchor_is_offered_before_the_session_one() -> None:
    """Order is the teaching: a reader takes the first workable flag."""
    order = [flag for _dest, flag in SELECTOR_ARGUMENTS]
    assert order.index("--item") < order.index("--session")
    assert order[0] == "--item"


@pytest.mark.parametrize("flag", ANCHOR_FLAGS)
def test_no_anchor_is_described_as_narrowing(flag: str) -> None:
    assert "Keep recipients" not in _block(flag), f"{flag} reads like a filter"
