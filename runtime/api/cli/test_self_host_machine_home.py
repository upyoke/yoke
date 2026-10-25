"""A default self-host bundle belongs to the machine, outside projects."""

from pathlib import Path
import subprocess

import pytest

from yoke_cli.config import machine_uninstall_inventory as inventory
from yoke_cli.config import onboard_self_host_server
from yoke_cli.self_host import bundle, teardown


@pytest.mark.parametrize("override", [False, True])
def test_default_bundle_ignores_project_directory(tmp_path, monkeypatch, override):
    home = tmp_path / "user"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.delenv("YOKE_MACHINE_HOME", raising=False)
    machine_home = home / ".yoke"
    if override:
        machine_home = tmp_path / "selected-machine"
        monkeypatch.setenv("YOKE_MACHINE_HOME", str(machine_home))
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    expected = machine_home / "yoke-server"

    setup = onboard_self_host_server.new_setup(config_path=str(machine_home / "config.json"))
    assert setup.directory == expected.resolve()
    report = bundle.write_bundle(admin_name="Ada Lovelace", image="example.test/server:pin")
    assert report["directory"] == str(expected.resolve())
    assert not (project / "yoke-server").exists()
    assert bundle.validate_existing_bundle() == expected.resolve()
    assert bundle.protect_existing_bundle()["directory"] == str(expected.resolve())

    # Docker labels carry the absolute location, so uninstall finds the bundle
    # under the machine home just as it does an explicit operator directory.
    monkeypatch.setattr(inventory.shutil, "which", lambda _: "/bin/docker")
    monkeypatch.setattr(
        inventory.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args, 0, "container\n" if "ps" in args else str(expected) + "\n", ""
        ),
    )
    directories, error = inventory._self_host_directories()
    assert directories == (expected.resolve(),)
    assert not error

    calls = []
    monkeypatch.setattr(teardown, "_WHICH", lambda _: "/bin/docker")
    monkeypatch.setattr(
        teardown, "_RUN",
        lambda args, **kwargs: calls.append((args, kwargs["cwd"]))
        or subprocess.CompletedProcess(args, 0, "", ""),
    )
    result = teardown.tear_down(remove_bundle=True, keep_connection=True)
    assert result["ok"]
    assert calls[0][1] == expected.resolve()
    assert not expected.exists()
    assert project.is_dir()
