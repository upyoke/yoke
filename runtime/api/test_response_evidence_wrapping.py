"""The ASCII fast path preserves the existing Rich width contract."""

import pytest
from rich.console import Console
from rich.text import Text

from yoke_contracts.response_evidence import wrapped_lines


@pytest.mark.parametrize(
    "text",
    [
        "",
        "\n",
        "\n\n",
        "a" * 80,
        "a" * 81,
        "a" * 161,
        "word " * 40,
        " " * 100,
        "  indented  \nplain\n",
        "\tindented\n" + "x" * 79 + "\t",
        "\x1b[31mred\x1b[0m",
        "界" * 70,
        "👩‍💻" * 45,
        "e\u0301" * 85,
        "line\r\nother\rfinal",
        "control\x00character",
    ],
)
def test_wrapped_lines_matches_rich_for_width_boundaries_and_special_text(text):
    console = Console(width=80, color_system=None)
    expected = sum(
        max(1, len(Text.from_ansi(line).wrap(console, 80, overflow="fold")))
        for line in text.splitlines()
    )
    assert wrapped_lines(text) == expected
