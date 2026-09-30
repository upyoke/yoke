"""Remote Linux restore cleanup stays confined to Yoke-owned services."""

import os
import subprocess
from types import SimpleNamespace
from yoke_harness.ssh_linux_baseline import _ARCHIVE_PROGRAM


def test_remote_reset_program_is_compilable_and_proves_only_yoke_service_removal(
    monkeypatch,
):
    from yoke_harness.ssh_linux_reset_cleanup import RESET_WRITERS_PROGRAM
    from yoke_harness.ssh_mac_full_reset_contract import (
        COMPOSE_PROJECT_LABEL,
        SELF_HOST_COMPOSE_PROJECT,
    )
    import shutil
    import pathlib

    commands = []
    inventories = {"containers": ["container-id", ""], "volumes": ["volume-id", ""]}

    def run(argv, **kwargs):
        commands.append(argv)
        output = ""
        if "list-units" in argv:
            output = "yoke-server.service loaded active running Yoke\n"
        elif argv[:3] == ["docker", "ps", "-aq"]:
            output = inventories["containers"].pop(0)
        elif argv[:3] == ["docker", "volume", "ls"]:
            output = inventories["volumes"].pop(0)
        return subprocess.CompletedProcess(argv, 0, output, "")

    class EmptyProc:
        def iterdir(self):
            return iter(())

    def path(value):
        assert value == "/proc"
        return EmptyProc()

    def refuse(reason):
        raise AssertionError(reason)

    # Compile the exact remote program, including its indented cleanup insertion.
    remote = _ARCHIVE_PROGRAM.replace(
        "        # STOP_YOKE_WRITERS",
        "\n".join("        " + line for line in RESET_WRITERS_PROGRAM.splitlines()),
    )
    compile(remote, "<remote-linux-home-restore>", "exec")
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(shutil, "which", lambda value: "/usr/bin/" + value)
    exec(
        RESET_WRITERS_PROGRAM,
        {
            "shutil": shutil,
            "pathlib": SimpleNamespace(Path=path),
            "home": pathlib.Path("/home/tester"),
            "os": os,
            "refuse": refuse,
        },
    )
    assert [
        "systemctl",
        "--user",
        "disable",
        "--now",
        "yoke-server.service",
    ] in commands
    label = "label=" + COMPOSE_PROJECT_LABEL + "=" + SELF_HOST_COMPOSE_PROJECT
    inventories_seen = [argv for argv in commands if "--filter" in argv]
    assert len(inventories_seen) == 4
    assert all(label in argv for argv in inventories_seen)
    assert ["docker", "rm", "--force", "--", "container-id"] in commands
    assert ["docker", "volume", "rm", "--force", "--", "volume-id"] in commands
