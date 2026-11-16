"""Native Windows hosting refuses before touching host state or Docker."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yoke_cli.commands import self_host, self_host_import, self_host_teardown
from yoke_cli.config import onboard_self_host_server as server
from yoke_cli.self_host import native_windows


COMMANDS = [
    (self_host.self_host_init, ["--admin-name", "Ada"]),
    (self_host.self_host_init, ["--admin-name", "Ada", "--start"]),
    (self_host.self_host_init, ["--protect-existing", "--start"]),
    (self_host.self_host_upgrade, ["--yes"]),
    (self_host_import.self_host_import, ["missing.tar", "--yes"]),
    (self_host_import.self_host_import, ["--recover-credential"]),
    (self_host_teardown.self_host_teardown, ["--destroy-universe", "--yes"]),
]


def _snapshot(root):
    return {
        str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
        for path in root.rglob("*")
    }


def _windows(monkeypatch):
    # Replacing the module's reference leaves pathlib and pytest's OS facts intact.
    monkeypatch.setattr(native_windows, "sys", SimpleNamespace(platform="win32"))


def _assert_recovery(message):
    assert "self_host_native_windows_requires_wsl2" in message
    assert "WSL2" in message
    assert "wsl --install -d Ubuntu" in message
    assert "install Yoke inside that distribution" in message
    assert "Docker Engine with Compose" in message
    assert "rerun" in message


@pytest.mark.parametrize("command,args", COMMANDS)
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("json_mode", [False, True])
def test_commands_preserve_host_state(
    monkeypatch, tmp_path, capsys, command, args, existing, json_mode
):
    _windows(monkeypatch)
    target = tmp_path / "bundle"
    if existing:
        (target / "secrets").mkdir(parents=True)
        (target / ".env").write_bytes(b"operator config")
        (target / "secrets" / "token").write_bytes(b"private credential")
    before = _snapshot(tmp_path)
    unexpected = Mock(side_effect=AssertionError("must refuse before host operations"))
    for owner, name in [
        (self_host.prerequisites, "check"),
        (self_host.upgrade, "plan_upgrade"),
        (self_host_import.bundle, "validate_existing_bundle"),
        (self_host_teardown.teardown, "tear_down"),
        (self_host.runtime, "start_bundle"),
    ]:
        monkeypatch.setattr(owner, name, unexpected)
    assert command([*args, "--dir", str(target), *(["--json"] if json_mode else [])]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    _assert_recovery(output.err)
    assert "private credential" not in output.err
    unexpected.assert_not_called()
    assert _snapshot(tmp_path) == before


def test_guided_hosting_refuses_before_loading_or_provisioning(monkeypatch, tmp_path):
    _windows(monkeypatch)
    unexpected = Mock(side_effect=AssertionError("must refuse before host operations"))
    monkeypatch.setattr(server.server_image_repository, "configured", unexpected)
    monkeypatch.setattr(server.server_image_repository, "save", unexpected)
    monkeypatch.setattr(server.bundle, "write_bundle", unexpected)
    monkeypatch.setattr(server.runtime, "start_bundle", unexpected)
    config = tmp_path / "config.json"
    config.write_text('{"operator": "preserve"}')
    target = tmp_path / "bundle"
    before = _snapshot(tmp_path)
    with pytest.raises(native_windows.NativeWindowsError) as refused:
        server.new_setup(config_path=str(config), directory=str(target))
    _assert_recovery(str(refused.value))
    setup = server.SelfHostSetup(directory=target, config_path=str(config))
    with pytest.raises(server.SelfHostSetupError) as refused:
        server.provision(setup, SimpleNamespace(executable="docker"))
    _assert_recovery(str(refused.value))
    assert refused.value.code == native_windows.NativeWindowsError.code
    unexpected.assert_not_called()
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_linux_and_mac_guard_allows_existing_host_path(monkeypatch, platform):
    monkeypatch.setattr(native_windows, "sys", SimpleNamespace(platform=platform))
    assert native_windows.refuse() is None
