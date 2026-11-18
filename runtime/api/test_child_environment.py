"""Children retain OS startup support without inheriting operator authority."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from yoke_contracts.process_environment import WINDOWS_SYSTEM_VARIABLES
from yoke_contracts.testing import child_environment


@pytest.mark.parametrize("separator", [":", ";"])
def test_minimal_environment_keeps_system_variables_and_directory_boundaries(
    monkeypatch, separator
):
    values = {
        "SYSTEMROOT": "Windows",
        "SYSTEMDRIVE": "C:",
        "WINDIR": "Windows",
        "COMSPEC": "cmd.exe",
        "PATHEXT": ".COM;.EXE;.BAT;.CMD",
        "APPDATA": "Users/me/AppData/Roaming",
        "LOCALAPPDATA": "Users/me/AppData/Local",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("YOKE_SESSION_ID", "operator-session")
    monkeypatch.setenv("YOKE_API_TOKEN", "operator-secret")
    monkeypatch.setenv("PATH", "unwanted-operator-tools")
    monkeypatch.setattr(child_environment.os, "pathsep", separator)
    monkeypatch.setattr(child_environment.os, "defpath", separator.join(("default-a", "default-b")))
    monkeypatch.setattr(child_environment.sys, "executable", str(Path("python") / "python.exe"))
    tools = (Path("mock"), Path("scripts"))
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
    for name in WINDOWS_SYSTEM_VARIABLES:
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


def test_minimal_child_can_import_profile_reading_libraries():
    """pyfiglet reads os.environ["APPDATA"] at import on Windows."""
    subprocess.run(
        [sys.executable, "-c", "import pyfiglet, platformdirs; platformdirs.user_data_dir()"],
        env=child_environment.minimal_child_environment(),
        capture_output=True, text=True, check=True, timeout=30,
    )


def test_delegated_service_child_keeps_os_startup_without_caller_authority(monkeypatch):
    from yoke_core.api import service_client_shared_io

    values = {
        **{name: f"system-{name}" for name in WINDOWS_SYSTEM_VARIABLES},
        "HOME": "caller-home",
        "USERPROFILE": "caller-profile",
        "YOKE_MACHINE_HOME": "caller-machine-home",
        "YOKE_MACHINE_CONFIG_FILE": "caller-config.json",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("YOKE_API_TOKEN", "operator-secret")
    monkeypatch.setenv("YOKE_SESSION_ID", "operator-session")
    monkeypatch.setattr(service_client_shared_io, "_subprocess_backend_env", lambda: {})
    env = service_client_shared_io._subprocess_service_env()
    assert {name: env[name] for name in values} == values
    assert "YOKE_API_TOKEN" not in env
    assert "YOKE_SESSION_ID" not in env


def test_merge_child_has_an_isolated_native_profile(tmp_path, monkeypatch):
    from dataclasses import fields
    from types import SimpleNamespace
    from runtime.api import merge_worktree_full_test_support as support

    monkeypatch.setattr(support, "os", SimpleNamespace(
        name="nt", environ=os.environ, pathsep=os.pathsep,
    ))
    monkeypatch.setenv("APPDATA", "operator-profile")
    values = {field.name: tmp_path / field.name for field in fields(support.MergeEnv)}
    values.update(tmpdir=tmp_path, test_path=str(Path(sys.executable).parent))
    env = support.MergeEnv(**values).env()
    home = Path(env["USERPROFILE"])
    assert home == Path(env["HOME"]) == tmp_path / "home"
    for name in ("APPDATA", "LOCALAPPDATA"):
        assert Path(env[name]).is_relative_to(home)
        assert Path(env[name]).is_dir()
    assert env["TEMP"] == env["TMP"] == env["TMPDIR"] == str(tmp_path / "tmp")
    subprocess.run(
        [sys.executable, "-c", "import pyfiglet"],
        env=env, check=True, capture_output=True, timeout=30,
    )
