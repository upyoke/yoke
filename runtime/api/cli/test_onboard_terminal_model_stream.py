"""Terminal replay consumes a stream, including Textual's Windows chunks."""

import pytest

pytest.importorskip("textual")

from runtime.api.cli.onboard_terminal_model import TerminalModel  # noqa: E402


@pytest.mark.parametrize(
    "sequence",
    [
        "\x1b[0m",
        "\x1b[2J",
        "\x1b[2;3H",
        "\x1b[?25l",
        "\x1b]0;title\x07",
        "\x1b]0;title\x1b\\",
    ],
)
def test_escape_sequences_survive_every_write_boundary(sequence: str) -> None:
    stream = "before" + sequence + "after"
    expected = TerminalModel(40, 4)
    expected.feed(stream)
    for boundary in range(1, len(stream)):
        actual = TerminalModel(40, 4)
        actual.feed(stream[:boundary])
        actual.feed(stream[boundary:])
        assert actual.rows == expected.rows, (sequence, boundary)
        assert (actual.row, actual.col) == (expected.row, expected.col)


def test_windows_frame_chunk_boundary_preserves_sgr() -> None:
    # Textual App._display writes at most 8192 characters per call on Windows.
    stream = "\x1b[0m" * 1638 + " " + "\x1b[0m\x1b[2;1HReady"
    actual = TerminalModel(171, 43)
    for offset in range(0, len(stream), 8192):
        actual.feed(stream[offset : offset + 8192])
    assert actual.rows == ["", "Ready"] + [""] * 41


def test_escape_sequences_survive_single_character_writes() -> None:
    actual = TerminalModel(20, 3)
    for char in "old\x1b[2J\x1b[2;3H\x1b[0mnew\x1b]0;title\x1b\\":
        actual.feed(char)
    assert actual.rows == ["", "  new", ""]
