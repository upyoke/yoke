"""Terminal.app bridge AppleScript: literal non-ASCII text and focus on open."""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys

import pytest

from yoke_harness.ssh_mac_terminal_app import (
    open_terminal_app_window,
    send_terminal_app_keys,
)

PROMPT = "❯"
# The field-note shape: AppleScript rejects `\u` after an escaped quote.
COMMAND = (
    "/usr/bin/osascript -e "
    f"'tell application \"System Events\" to keystroke \"{PROMPT}\"'"
)


class _Host:
    """Answer each osascript call the way a healthy Mac does; keep each script."""

    def __init__(self) -> None:
        self.scripts: list[str] = []

    def __call__(self, command: str, **_kwargs) -> subprocess.CompletedProcess[str]:
        argv = shlex.split(command)
        assert argv[:2] == ["/usr/bin/osascript", "-e"]
        script = argv[2]
        self.scripts.append(script)
        if "whose frontmost is true" in script:
            stdout = "Terminal|7"
        elif "do script" in script:
            stdout = "7"
        else:
            stdout = "true"
        return subprocess.CompletedProcess(command, 0, stdout, "")


def _assert_literal(script: str, text: str) -> None:
    assert text in script
    assert "\\u" not in script


def _assert_compiles(script: str, tmp_path) -> None:
    """The defect was an AppleScript compile error, so compile when we can."""
    if sys.platform != "darwin" or shutil.which("osacompile") is None:
        return
    result = subprocess.run(
        ["osacompile", "-o", str(tmp_path / "bridge.scpt"), "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_window_command_keeps_non_ascii_literal(tmp_path):
    host = _Host()

    launch = open_terminal_app_window(host, command=COMMAND)

    assert launch.window_id == 7
    _assert_compiles(host.scripts[0], tmp_path)
    _assert_literal(host.scripts[0], PROMPT)


@pytest.mark.parametrize(
    "key",
    [COMMAND, f"paste_file:/tmp/{PROMPT}.txt"],
    ids=["keystroke", "paste_file"],
)
def test_typed_keys_keep_non_ascii_literal(key, tmp_path):
    host = _Host()

    delivery = send_terminal_app_keys(host, window_id=7, keys=[key])

    assert delivery.delivered is True
    _assert_compiles(host.scripts[-1], tmp_path)
    _assert_literal(host.scripts[-1], PROMPT)


def test_window_without_bounds_opens_behind_the_frontmost_app():
    host = _Host()

    open_terminal_app_window(host, command="true")

    assert "activate" not in host.scripts[0].splitlines()


def test_window_with_bounds_activates_before_it_is_raised():
    host = _Host()

    open_terminal_app_window(host, command="true", bounds=(0, 25, 800, 600))

    lines = host.scripts[0].splitlines()
    assert lines.count("activate") == 1
    assert lines.index("activate") < lines.index("set index of targetWindow to 1")
