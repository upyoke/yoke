"""Remote Linux restore quiesces home programs and scopes service removal."""

import os
import json
import subprocess
import sys
import pytest
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
    reloaded = False

    def run(argv, **kwargs):
        nonlocal reloaded
        commands.append(argv)
        output = ""
        if "daemon-reload" in argv:
            reloaded = True
        elif "list-units" in argv and not reloaded:
            output = "yoke-server.service loaded active running Yoke\n"
        elif argv[0] == "loginctl":
            output = "no"
        elif argv[:2] == ["docker", "inspect"]:
            output = "image-id"
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
        "            # STOP_YOKE_WRITERS",
        "\n".join("            " + line for line in RESET_WRITERS_PROGRAM.splitlines()),
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
        "stop",
        "yoke-server.service",
    ] in commands
    label = "label=" + COMPOSE_PROJECT_LABEL + "=" + SELF_HOST_COMPOSE_PROJECT
    inventories_seen = [argv for argv in commands if "--filter" in argv]
    assert len(inventories_seen) == 4
    assert all(label in argv for argv in inventories_seen)
    assert ["docker", "rm", "--force", "--", "container-id"] in commands
    assert ["docker", "volume", "rm", "--force", "--", "volume-id"] in commands
    assert ["docker", "image", "rm", "--", "image-id"] in commands


@pytest.mark.parametrize("survives", [False, True])
def test_reset_removes_relay_files_and_reloads_ghost_units(
    monkeypatch, tmp_path, survives
):
    import pathlib
    import shutil
    from yoke_harness.ssh_linux_reset_services import RESET_SERVICES_PROGRAM

    root = tmp_path / "units"
    root.mkdir()
    relay = root / "com.upyoke.relay.local.service"
    relay.write_text("[Service]\nExecStart=/missing/yoke\n")
    wants = root / "default.target.wants"
    wants.mkdir()
    link = wants / relay.name
    link.symlink_to(relay)
    other = root / "another-app.service"
    other.write_text("preserve this")
    commands = []
    reloaded = False
    ghost = "com.upyoke.relay.deleted.service"

    def bounded(argv, **kwargs):
        nonlocal reloaded
        commands.append(argv)
        output = ""
        if argv[0] == "systemd-analyze":
            output = str(root) + "\n"
        elif "daemon-reload" in argv:
            reloaded = True
        elif "list-units" in argv and (not reloaded or survives):
            output = f"{ghost} loaded activating auto-restart Yoke\n"
        elif "list-unit-files" in argv and relay.exists():
            output = relay.name + " enabled\n"
        elif argv[0] == "loginctl":
            output = "yes"  # unrelated user services may legitimately use linger
        return subprocess.CompletedProcess(argv, 0, output, "")

    def refuse(reason, entry=None):
        raise RuntimeError(reason)

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/" + name)
    namespace = {
        "shutil": shutil,
        "pathlib": pathlib,
        "home": tmp_path,
        "os": os,
        "bounded": bounded,
        "refuse": refuse,
    }
    if survives:
        with pytest.raises(RuntimeError, match="service_absence_not_proved"):
            exec(RESET_SERVICES_PROGRAM, namespace)
    else:
        exec(RESET_SERVICES_PROGRAM, namespace)
        assert namespace["service_cleanup"]["linger"] == "yes"
    assert not relay.exists() and not link.is_symlink()
    assert other.read_text() == "preserve this"
    assert ["systemctl", "--user", "stop", ghost] in commands
    reset = ["systemctl", "--user", "reset-failed", ghost, relay.name]
    reload = ["systemctl", "--user", "daemon-reload"]
    assert commands.index(reset) < commands.index(reload)
    assert not any("disable-linger" in argv for argv in commands)


@pytest.mark.parametrize(
    "name", ["yoke-server.service", "com.upyoke.relay.local.service"]
)
def test_golden_refuses_yoke_service_definitions_before_sealing(tmp_path, name):
    if os.getuid() == 0:
        pytest.skip("archive fixture requires the contract's non-root user")
    home = tmp_path / "home"
    units = home / ".config/systemd/user"
    units.mkdir(parents=True)
    (units / name).write_text("[Service]\nExecStart=/missing/yoke\n")
    golden = tmp_path / "golden"
    result = subprocess.run(
        [sys.executable, "-c", _ARCHIVE_PROGRAM, "capture", str(home), str(golden)],
        input="[]",
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home)},
        check=False,
    )
    assert result.returncode == 64
    assert (
        json.loads(result.stdout)["reason"] == "golden_baseline_contains_yoke_service"
    )
    assert not golden.exists()
    assert (units / name).is_file()


@pytest.mark.parametrize("outcome", ["stopped", "pid_reused", "refused", "respawned"])
@pytest.mark.parametrize("home_program", ["yoke", "deleted_harness"])
def test_linux_reset_stops_home_program_descendants_and_proves_process_identity(
    monkeypatch, outcome, home_program
):
    import shutil
    import time
    from pathlib import Path
    from yoke_harness.ssh_linux_reset_cleanup import RESET_WRITERS_PROGRAM

    records = {
        11: {
            "parent": 1,
            "start": "100",
            "args": ["/home/tester/.yoke/bin/server"]
            if home_program == "yoke"
            else ["codex", "app-server", "--managed-daemon"],
            "executable": "/usr/bin/python3"
            if home_program == "yoke"
            else "/home/tester/.codex/bin/codex (deleted)",
            "uid": 1000,
        },
        12: {"parent": 11, "start": "200", "args": ["/usr/bin/sleep"], "uid": 1000},
        13: {
            "parent": 1,
            "start": "300",
            "args": ["/usr/bin/other", "/home/tester-sibling/data"],
            "uid": 1000,
        },
        14: {"parent": 11, "start": "400", "args": ["/usr/bin/foreign"], "uid": 2000},
    }
    killed = []

    class ProcPath:
        def __init__(self, value):
            self.value = str(value)
            self.name = self.value.rsplit("/", 1)[-1]

        def iterdir(self):
            return iter(ProcPath(f"/proc/{pid}") for pid in records)

        def stat(self):
            return SimpleNamespace(st_uid=self.record()["uid"])

        def record(self):
            pid = int(self.value.split("/")[2])
            if pid not in records:
                raise FileNotFoundError()
            return records[pid]

        def __truediv__(self, value):
            return ProcPath(self.value + "/" + value)

        def read_text(self):
            record = self.record()
            return "(process) " + " ".join(
                ["S", str(record["parent"]), *["0"] * 17, record["start"]]
            )

        def read_bytes(self):
            return bytes([0]).join(value.encode() for value in self.record()["args"])

    def kill(pid, sig):
        killed.append((pid, sig))
        if outcome in {"stopped", "respawned"} or (
            outcome == "pid_reused" and pid == 12
        ):
            records.pop(pid)
            if outcome == "respawned":
                records[15] = {
                    "parent": 1,
                    "start": "500",
                    "args": ["/home/tester/.cursor/bin/node"],
                    "uid": 1000,
                }
        elif outcome == "pid_reused":
            records[pid]["start"] = "new-process"
            records[pid]["args"] = ["/usr/bin/unrelated"]
            records[pid]["executable"] = "/usr/bin/unrelated"

    clock = [0.0]
    monkeypatch.setattr(shutil, "which", lambda value: None)
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay)
    )

    def refuse(reason):
        raise RuntimeError(reason)

    namespace = {
        "home": Path("/home/tester"),
        "shutil": shutil,
        "os": SimpleNamespace(
            getuid=lambda: 1000,
            getpid=lambda: 99,
            kill=kill,
            readlink=lambda path: path.record().get("executable", "/usr/bin/program"),
        ),
        "pathlib": SimpleNamespace(Path=ProcPath),
        "refuse": refuse,
    }
    if outcome in {"refused", "respawned"}:
        with pytest.raises(RuntimeError, match="linux_home_writers_stop_not_proved"):
            exec(RESET_WRITERS_PROGRAM, namespace)
    else:
        exec(RESET_WRITERS_PROGRAM, namespace)
    assert {pid for pid, sig in killed} == {11, 12}
    assert 13 in records and 14 in records
    if outcome == "pid_reused":
        assert len([event for event in killed if event[0] == 11]) == 1
        assert records[11]["start"] == "new-process"
