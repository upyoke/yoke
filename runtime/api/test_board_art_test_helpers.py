"""Shared fixtures and constants for board-art tests.

Imported by ``test_board_art.py`` and ``test_board_art_render.py``.
"""

from __future__ import annotations

import pytest

from yoke_contracts.board.art import (
    BLACK,
    WHITE,
    parse_art_config,
)


# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

MINI_MASTER_MAP = [
    BLACK + WHITE + WHITE + WHITE + BLACK,
    BLACK + WHITE + BLACK + WHITE + BLACK,
    BLACK + WHITE + WHITE + WHITE + BLACK,
]

MINI_CONFIG = """\
## Master Map
{master_map}

# weight-disabled:2
## Emoji
{emoji_1}

# weight:5
## Emoji
{emoji_2}

## ASCII
line one of ascii
line two of ascii

## Mixed
mixed line one
mixed line two
""".format(
    master_map="\n".join(MINI_MASTER_MAP),
    emoji_1="\n".join([
        BLACK * 6,
        WHITE + WHITE + BLACK + WHITE + WHITE + BLACK,
        BLACK * 6,
    ]),
    emoji_2="\n".join([
        BLACK * 6,
        WHITE + BLACK + WHITE + BLACK + WHITE + BLACK,
        BLACK * 6,
    ]),
)


@pytest.fixture
def config_file(tmp_path):
    """Write a minimal config file and return its path."""
    p = tmp_path / "config"
    p.write_text(MINI_CONFIG, encoding="utf-8")
    return str(p)


@pytest.fixture
def art_config(config_file):
    """Parse the minimal config fixture."""
    return parse_art_config(config_file)
