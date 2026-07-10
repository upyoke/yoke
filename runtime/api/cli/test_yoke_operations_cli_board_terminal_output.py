"""Terminal rendering contracts for ``yoke board`` output."""

from __future__ import annotations

from yoke_cli.commands.board_terminal_output import board_print_content


_BOARD_METADATA = {
    "scope": "2",
    "repo_root": "/repo",
    "board_path": "/repo/.yoke/BOARD.md",
}


def test_board_print_content_keeps_rich_output_in_regular_terminal() -> None:
    rendered = board_print_content(
        "🏆 BOARD █ CONTENT └ done\n",
        _BOARD_METADATA,
        env={"TERM": "xterm-256color", "TERM_PROGRAM": "Apple_Terminal"},
    )
    assert "Yoke board terminal mode: plain" not in rendered
    assert "🏆 BOARD █ CONTENT └ done" in rendered


def test_board_print_content_explains_forced_plain_mode() -> None:
    rendered = board_print_content(
        "\x1b[32m🏆 BOARD █ CONTENT └ done\x1b[0m\n",
        _BOARD_METADATA,
        env={"TERM": "xterm-256color", "YOKE_BOARD_PLAIN": "1"},
    )
    assert "YOKE_BOARD_PLAIN is set" in rendered
    assert "\x1b[" not in rendered
    assert "🏆" not in rendered
    assert "* BOARD # CONTENT + done" in rendered
