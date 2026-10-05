"""Machine inventory never tears down source installs or unsafe homes."""

import json
import subprocess
import os
import sys
from pathlib import Path

import pytest

from yoke_cli.config import machine_uninstall_inventory as inventory
from yoke_cli.config import machine_uninstall_workers as workers
from yoke_cli.project_install.files import MANIFEST_REL
from yoke_contracts.process_ancestry import process_start_time


@pytest.fixture
def machine(tmp_path, monkeypatch):
    home = tmp_path / "machine"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(home / "config.json"))
    monkeypatch.setattr(
        inventory.install_binding, "detect", lambda: {"kind": "packaged-wheel"}
    )
    monkeypatch.setattr(
        inventory.local_universe_setup, "local_cluster_initialized", lambda: False
    )
    monkeypatch.setattr(inventory, "_self_host_directories", lambda: ((), ""))
    return home


def test_source_checkout_refuses_before_machine_reads(monkeypatch):
    monkeypatch.setattr(
        inventory.install_binding,
        "detect",
        lambda: {
            "kind": inventory.install_binding.KIND_SOURCE_CHECKOUT,
            "checkout_root": "/source/yoke",
        },
    )
    monkeypatch.setattr(
        inventory.machine_config,
        "load_config",
        lambda *args: pytest.fail("no config read"),
    )
    with pytest.raises(inventory.UninstallError, match="uninstall_source_checkout"):
        inventory.inspect()


def test_only_registered_installed_checkouts_are_listed(machine, tmp_path):
    project, other = tmp_path / "project", tmp_path / "other"
    manifest = project / MANIFEST_REL
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}")
    (machine / "config.json").write_text(
        json.dumps(
            {
                "projects": [
                    {"checkout": str(project), "project_id": 1, "env": "one"},
                    {"checkout": str(project), "project_id": 1, "env": "two"},
                    {"checkout": str(other), "project_id": 2},
                ],
                "connections": {
                    "one": {"transport": "https"},
                    "admin": {"transport": "local-postgres", "prod": True},
                },
            }
        )
    )
    result = inventory.inspect()
    assert result.projects == (project,)
    assert result.relay_envs == ("one",)
    assert not result.owns_data


@pytest.mark.parametrize("kind", ["user_home", "parent_of_checkout", "symlink"])
def test_unsafe_home_refuses(tmp_path, kind):
    home = tmp_path / "machine"
    home.mkdir()
    projects = []
    if kind == "user_home":
        home = Path.home()
    elif kind == "parent_of_checkout":
        projects = [home / "repo"]
    else:
        link = tmp_path / "link"
        link.symlink_to(home, target_is_directory=True)
        home = link
    with pytest.raises(
        inventory.UninstallError, match="uninstall_(unsafe_home|home_symlink)"
    ):
        inventory._assert_safe_home(home, projects)


def test_inventory_is_read_only(machine):
    machine.chmod(0o750)
    before = machine.stat().st_mode
    inventory.inspect()
    assert machine.stat().st_mode == before


def test_docker_inventory_uses_self_host_marker_and_compose_path(tmp_path, monkeypatch):
    directory = tmp_path / "server"
    directory.mkdir()
    (directory / inventory.bundle.COMPOSE_FILE_NAME).write_text("services: {}")
    calls = []
    monkeypatch.setattr(inventory.shutil, "which", lambda name: "/bin/docker")

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(
            args, 0, "abc\n" if "ps" in args else str(directory) + "\n", ""
        )

    monkeypatch.setattr(inventory.subprocess, "run", run)
    directories, error = inventory._self_host_directories()
    assert directories == (directory,)
    assert not error
    assert "YOKE_SERVER_MODE=self-host" in calls[1][3]
    assert "com.docker.compose.project.working_dir" in calls[1][3]


def test_docker_failure_is_named_without_dumping_secret_streams(monkeypatch):
    monkeypatch.setattr(inventory.shutil, "which", lambda name: "/bin/docker")
    monkeypatch.setattr(
        inventory.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args, 1, "", "sensitive environment"
        ),
    )
    directories, error = inventory._self_host_directories()
    assert directories == ()
    assert "uninstall_docker_inventory_failed" in error
    assert "sensitive" not in error


@pytest.mark.parametrize("stale_identity", [False, True])
def test_worker_stop_checks_process_identity_before_signalling(
    tmp_path, monkeypatch, stale_identity
):
    from yoke_harness import session_launch_handles

    handles = tmp_path / "handles"
    handles.mkdir()
    monkeypatch.setattr(
        session_launch_handles, "native_handle_directory", lambda: handles
    )
    monkeypatch.setattr(workers.machine_config, "cache_dir", lambda: tmp_path / "cache")
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        record = {
            "pid": process.pid,
            "process_start_time": "stale identity"
            if stale_identity
            else process_start_time(process.pid),
        }
        assert record["process_start_time"]
        (handles / "owned.json").write_text(json.dumps(record))
        workers.stop(())
        if stale_identity:
            assert process.poll() is None
        else:
            assert process.wait(timeout=10) < 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def test_worker_stop_refuses_its_own_process_group(tmp_path, monkeypatch):
    from yoke_harness import session_launch_handles

    handles = tmp_path / "handles"
    handles.mkdir()
    monkeypatch.setattr(
        session_launch_handles, "native_handle_directory", lambda: handles
    )
    monkeypatch.setattr(workers.machine_config, "cache_dir", lambda: tmp_path / "cache")
    (handles / "shared.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "process_start_time": process_start_time(os.getpid()),
            }
        )
    )
    with pytest.raises(inventory.UninstallError, match="shared_process_group"):
        workers.stop(())
