"""Short ``yoke board`` adapter behavior."""


def test_board_shortcut_injects_print(monkeypatch):
    from yoke_cli.commands.adapters import board as board_mod

    captured: list = []
    monkeypatch.setattr(
        board_mod, "board_rebuild", lambda args: captured.append(args) or 0
    )
    board_mod.board([])
    assert captured == [["--print"]]


def test_board_shortcut_respects_explicit_mode(monkeypatch):
    from yoke_cli.commands.adapters import board as board_mod

    captured: list = []
    monkeypatch.setattr(
        board_mod, "board_rebuild", lambda args: captured.append(args) or 0
    )
    board_mod.board(["--json"])
    assert captured == [["--json"]]


def test_board_shortcut_registered_tool_shaped():
    from yoke_cli.commands.tool_shaped import resolve_tool_shaped

    resolved = resolve_tool_shaped(["board"])
    assert resolved is not None
