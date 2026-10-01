"""Tunnel-only desktop provisioning retains custom ports and refuses unsafe binds."""

import importlib.util
from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def provisioner():
    path = (
        Path(__file__).resolve().parents[3]
        / "packs/machine-qa/versions/1.3.0/files/ops/machine-qa/provision_linux_desktop.py"
    )
    spec = importlib.util.spec_from_file_location("desktop_provisioner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_listener_configuration_retains_module_ports_and_is_idempotent(provisioner):
    original = "; keep this comment\n[Globals]\nport=3389\n[Xorg]\nport=-1\n"
    configured = provisioner.localhost_config(original)
    assert "port=tcp://127.0.0.1:3389\n" in configured
    assert configured.startswith("; keep this comment\n")
    assert configured.endswith("[Xorg]\nport=-1\n")
    assert provisioner.localhost_config(configured) == configured


@pytest.mark.parametrize(
    "content", ["[Xorg]\nport=-1\n", "[Globals]\nport=1\nport=2\n"]
)
def test_ambiguous_listener_configuration_refuses(provisioner, content):
    with pytest.raises(
        provisioner.ProvisionFailure, match="listener_config_unavailable"
    ):
        provisioner.localhost_config(content)


@pytest.mark.parametrize(
    "output",
    [
        "",
        "malformed",
        "LISTEN 0 2 0.0.0.0:3389 0.0.0.0:*",
        "LISTEN 0 2 [::]:3389 [::]:*",
        "LISTEN 0 2 127.0.0.1:3389 0.0.0.0:*\nLISTEN 0 2 *:3389 *:*",
    ],
)
def test_listener_proof_rejects_missing_or_public_binding(provisioner, output):
    with pytest.raises(provisioner.ProvisionFailure, match="loopback_not_proved"):
        provisioner.prove_listener(output)


def test_listener_proof_accepts_only_loopback(provisioner):
    provisioner.prove_listener("LISTEN 0 2 127.0.0.1:3389 0.0.0.0:*")


def test_service_socket_startup_is_waited_for(provisioner, monkeypatch):
    outputs = iter(["", "LISTEN 0 2 127.0.0.1:3389 0.0.0.0:*"])
    monkeypatch.setattr(
        provisioner,
        "command",
        lambda argv: subprocess.CompletedProcess(argv, 0, stdout=next(outputs)),
    )
    monkeypatch.setattr(provisioner.time, "sleep", lambda seconds: None)
    provisioner.wait_for_listener()


def test_custom_desktop_session_is_preserved(provisioner, monkeypatch, tmp_path):
    monkeypatch.setattr(provisioner.platform, "system", lambda: "Linux")
    monkeypatch.setattr(provisioner.os, "getuid", lambda: 1001)
    monkeypatch.setattr(
        provisioner.platform,
        "freedesktop_os_release",
        lambda: {"ID": "ubuntu", "VERSION_ID": "24.04"},
    )
    monkeypatch.setattr(provisioner.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        provisioner,
        "command",
        lambda argv: subprocess.CompletedProcess(argv, 0),
    )
    session = tmp_path / ".xsession"
    session.write_text("exec another-desktop\n")
    with pytest.raises(provisioner.ProvisionFailure, match="session_conflict"):
        provisioner.prerequisites()
    assert session.read_text() == "exec another-desktop\n"
