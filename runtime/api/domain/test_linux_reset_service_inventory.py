"""Linux reset distinguishes an empty unit-file inventory from an outage."""

import os
import pathlib
import shutil
import subprocess

import pytest

from yoke_harness.ssh_linux_reset_services import RESET_SERVICES_PROGRAM


def run_cleanup(monkeypatch, tmp_path, *, inventory, ghost=True, survives=False):
    commands = []
    reloaded = False
    relay = "com.upyoke.relay.deleted.service"

    def bounded(argv, **kwargs):
        nonlocal reloaded
        commands.append(argv)
        if "list-unit-files" in argv:
            return subprocess.CompletedProcess(argv, *inventory)
        output = ""
        if "list-units" in argv and ghost and (not reloaded or survives):
            output = f"{relay} loaded activating auto-restart Yoke\n"
        elif "daemon-reload" in argv:
            reloaded = True
        elif argv[0] == "systemd-analyze":
            output = str(tmp_path) + "\n"
        elif argv[0] == "loginctl":
            output = "no\n"
        return subprocess.CompletedProcess(argv, 0, output, "")

    def refuse(reason, entry=None):
        raise RuntimeError(reason)

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/" + name)
    namespace = {
        "shutil": shutil,
        "pathlib": pathlib,
        "os": os,
        "bounded": bounded,
        "refuse": refuse,
    }
    return commands, namespace, relay


@pytest.mark.parametrize("empty_status", [0, 1])
@pytest.mark.parametrize("ghost", [False, True])
def test_reset_accepts_empty_definitions_and_evicts_loaded_fileless_relay(
    monkeypatch, tmp_path, empty_status, ghost
):
    other = tmp_path / "another-app.service"
    other.write_text("preserve this")
    commands, namespace, relay = run_cleanup(
        monkeypatch, tmp_path, inventory=(empty_status, "", ""), ghost=ghost
    )
    exec(RESET_SERVICES_PROGRAM, namespace)
    assert namespace["service_cleanup"] == {
        "removed_units": [relay] if ghost else [],
        "linger": "no",
    }
    reload = ["systemctl", "--user", "daemon-reload"]
    if ghost:
        stop = ["systemctl", "--user", "stop", relay]
        reset = ["systemctl", "--user", "reset-failed", relay]
        assert commands.index(stop) < commands.index(reset) < commands.index(reload)
    assert not any("disable" in argv or "sudo" in argv for argv in commands)
    assert other.read_text() == "preserve this"
    assert not any("disable-linger" in argv for argv in commands)


@pytest.mark.parametrize(
    "inventory",
    [
        (1, "", "Failed to connect to bus: No medium found\n"),
        (1, "yoke-server.service enabled\n", ""),
        (2, "", ""),
    ],
)
def test_reset_refuses_unavailable_or_partial_unit_file_inventory(
    monkeypatch, tmp_path, inventory
):
    commands, namespace, _ = run_cleanup(monkeypatch, tmp_path, inventory=inventory)
    with pytest.raises(RuntimeError, match="linux_yoke_service_inventory_unavailable"):
        exec(RESET_SERVICES_PROGRAM, namespace)
    assert not any("stop" in argv or "daemon-reload" in argv for argv in commands)


def test_reset_does_not_credit_a_surviving_fileless_relay(monkeypatch, tmp_path):
    _, namespace, _ = run_cleanup(
        monkeypatch, tmp_path, inventory=(1, "", ""), survives=True
    )
    with pytest.raises(RuntimeError, match="linux_yoke_service_absence_not_proved"):
        exec(RESET_SERVICES_PROGRAM, namespace)
