"""xrdp listens beyond loopback only behind a firewall confined to Tailscale."""

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "packages/yoke-harness/src/yoke_harness/host_provisioning"
)


def _load(monkeypatch, name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def listener(monkeypatch):
    return _load(monkeypatch, "linux_desktop_listener")


@pytest.mark.parametrize(
    ("address", "listen"),
    [("0.0.0.0", "tcp://:3390"), ("127.0.0.1", "tcp://127.0.0.1:3390")],
)
def test_listener_configuration_preserves_other_sections(listener, address, listen):
    content = "[Globals]\nport=3389\n[session]\nport=-1\n"
    assert listener.listener_config(content, 3390, address) == (
        f"[Globals]\nport={listen}\n[session]\nport=-1\n"
    )
    listener.prove_listener(f"LISTEN 0 2 {address}:3390 0.0.0.0:*", 3390, address)


def test_listener_configuration_refuses_ambiguous_globals(listener):
    with pytest.raises(listener.ProvisionFailure, match="listener_config_unavailable"):
        listener.listener_config("[Globals]\n", 3389, listener.ANY_ADDRESS)


@pytest.mark.parametrize(
    ("expected", "found"),
    [("127.0.0.1", "0.0.0.0"), ("127.0.0.1", "[::]"), ("0.0.0.0", "127.0.0.1")],
)
def test_listener_on_another_address_is_refused(listener, expected, found):
    with pytest.raises(listener.ProvisionFailure, match="listener_not_proved"):
        listener.prove_listener(f"LISTEN 0 2 {found}:3389 0.0.0.0:*", 3389, expected)


def test_missing_listener_is_refused(listener):
    with pytest.raises(listener.ProvisionFailure, match="found nothing"):
        listener.prove_listener("", 3389, listener.LOOPBACK)


def test_firewall_drops_rdp_outside_loopback_and_tailscale(listener):
    rules = listener.firewall_rules(3389)
    # The leading declare-then-delete makes a rerun replace the table whole.
    assert rules.startswith(
        "table inet yoke_desktop\ndelete table inet yoke_desktop\n"
    )
    assert 'iifname != { "lo", "tailscale0" } tcp dport 3389 drop' in rules
    assert "Before=xrdp.service" in listener.firewall_unit()
    assert listener.FIREWALL_RULES in listener.firewall_unit()


def test_firewall_install_persists_before_enabling(listener):
    calls = []
    listener.install_firewall(
        3389,
        lambda argv: calls.append(argv),
        lambda content, path, mode: calls.append((path, mode)),
    )
    assert calls == [
        ["sudo", "-n", "install", "-d", "-m", "0755", "/etc/yoke"],
        (listener.FIREWALL_RULES, "0644"),
        (listener.FIREWALL_UNIT, "0644"),
        ["sudo", "-n", "systemctl", "daemon-reload"],
        ["sudo", "-n", "systemctl", "enable", "yoke-desktop-firewall.service"],
        ["sudo", "-n", "systemctl", "restart", "yoke-desktop-firewall.service"],
    ]


def test_live_ruleset_proof(listener):
    live = (
        "table inet yoke_desktop {\n\tchain input {\n"
        "\t\ttype filter hook input priority filter - 10; policy accept;\n"
        '\t\tiifname != { "lo", "tailscale0" } tcp dport 3389 drop\n\t}\n}\n'
    )
    listener.prove_firewall(3389, live)
    with pytest.raises(listener.ProvisionFailure, match="firewall_not_proved"):
        listener.prove_firewall(3390, live)
    with pytest.raises(listener.ProvisionFailure, match="firewall_not_proved"):
        listener.prove_firewall(3389, "table inet filter {}\n")


@pytest.fixture
def wsl(monkeypatch):
    _load(monkeypatch, "linux_desktop_listener")
    _load(monkeypatch, "provision_linux_desktop")
    return _load(monkeypatch, "provision_windows_wsl_desktop")


@pytest.mark.parametrize("verify_only", [False, True])
def test_tailnet_exposure_confines_the_port_to_tailscale(wsl, monkeypatch, verify_only):
    seen = []

    def run(argv, **kwargs):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, "100.64.0.7\r\n", "")

    monkeypatch.setattr(wsl.subprocess, "run", run)
    assert wsl.expose_on_tailnet(3390, verify_only=verify_only) == "100.64.0.7"
    script = seen[0][-1]
    assert "-InterfaceAlias Tailscale" in script
    assert "connectaddress=127.0.0.1 connectport=$port" in script
    assert "$port=3390" in script
    assert f"'{'verify' if verify_only else 'apply'}' -eq 'apply'" in script


def test_tailnet_exposure_failure_is_named(wsl, monkeypatch):
    monkeypatch.setattr(
        wsl.subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv,
            1,
            "",
            "windows_wsl_tailnet_address_missing: start Tailscale on the Windows host\r\n",
        ),
    )
    with pytest.raises(Exception, match="^windows_wsl_tailnet_address_missing: start"):
        wsl.expose_on_tailnet(3390, verify_only=True)


def test_unnamed_tailnet_failure_names_the_recovery(wsl, monkeypatch):
    monkeypatch.setattr(
        wsl.subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 1, "", "Access denied"),
    )
    with pytest.raises(Exception, match="windows_wsl_tailnet_failed: run provisioning"):
        wsl.expose_on_tailnet(3390, verify_only=False)
