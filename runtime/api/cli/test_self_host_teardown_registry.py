"""Self-host teardown registration and argument validation work on every OS."""

import pytest

from yoke_cli.commands import self_host_teardown as teardown_commands
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_cli.self_host import teardown


def test_teardown_is_registered_as_a_tool_shaped_command() -> None:
    resolved, _extra = resolve_tool_shaped(("self-host", "teardown"))
    assert resolved is teardown_commands.self_host_teardown


def test_teardown_has_no_unsafe_single_connection_selector(capsys) -> None:
    rc = teardown_commands.self_host_teardown(["--connection", "self-host"])

    assert rc == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_teardown_refuses_a_directory_that_is_not_a_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(teardown, "_WHICH", lambda _name: "/usr/bin/docker")

    with pytest.raises(teardown.SelfHostTeardownError) as raised:
        teardown.tear_down(directory=str(tmp_path))

    assert "--dir PATH" in str(raised.value)
