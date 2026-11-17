"""Children retain OS startup support without inheriting operator authority."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from yoke_contracts.testing import child_environment


@pytest.mark.parametrize("separator", [":", ";"])
def test_minimal_environment_keeps_system_variables_and_directory_boundaries(
    tmp_path, monkeypatch, separator
):
    values = {
        "SYSTEMROOT": str(tmp_path / "Windows"),
        "SYSTEMDRIVE": "C:",
        "WINDIR": str(tmp_path / "Windows"),
        "COMSPEC": str(tmp_path / "cmd.exe"),
        "PATHEXT": ".COM;.EXE;.BAT;.CMD",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("YOKE_SESSION_ID", "operator-session")
    monkeypatch.setenv("YOKE_API_TOKEN", "operator-secret")
    monkeypatch.setenv("PATH", "unwanted-operator-tools")
    monkeypatch.setattr(child_environment.os, "pathsep", separator)
    monkeypatch.setattr(child_environment.os, "defpath", separator.join(("default-a", "default-b")))
    tools = (tmp_path / "mock", tmp_path / "scripts")
    env = child_environment.minimal_child_environment((*tools, tools[0]))
    assert {name: env[name] for name in values} == values
    assert set(env) == {*values, "PATH"}
    assert env["PATH"].split(separator) == [
        *(str(path) for path in tools),
        str(Path(sys.executable).parent),
        str(Path(values["SYSTEMROOT"]) / "System32"),
        "default-a", "default-b",
    ]


def test_minimal_environment_without_windows_variables(monkeypatch):
    for name in child_environment.WINDOWS_SYSTEM_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    env = child_environment.minimal_child_environment()
    assert set(env) == {"PATH"}
    assert str(Path(sys.executable).parent) in env["PATH"].split(os.pathsep)


def test_minimal_child_can_initialize_networking():
    result = subprocess.run(
        [sys.executable, "-c", (
            "import json, socket, ssl; "
            "ssl.create_default_context(); "
            "print(json.dumps(bool(socket.getaddrinfo('localhost', 443))))"
        )],
        env=child_environment.minimal_child_environment(),
        capture_output=True, text=True, check=True, timeout=30,
    )
    assert json.loads(result.stdout) is True
