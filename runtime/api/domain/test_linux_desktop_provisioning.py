"""Tunnel-only desktop provisioning retains custom ports and refuses unsafe binds."""

import importlib.util
from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def provisioner():
    path = (
        Path(__file__).resolve().parents[3]
        / "packages/yoke-harness/src/yoke_harness/host_provisioning/provision_linux_desktop.py"
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


def test_default_app_selection_converges_without_erasing_other_helpers(provisioner):
    original = (
        "FileManager=thunar\nWebBrowser=chromium\n"
        "TerminalEmulator=missing\n TerminalEmulator = other\n"
    )
    selected = provisioner.helper_settings(original)
    assert selected == (
        "FileManager=thunar\nTerminalEmulator=xfce4-terminal\n"
        "WebBrowser=yoke-identity-browser\n"
    )
    assert provisioner.helper_settings(selected) == selected


@pytest.mark.parametrize(
    ("fault", "reason"),
    [
        (None, None),
        ("xfce4-helpers", "packages_not_proved"),
        ("xdg-utils", "packages_not_proved"),
        ("libgtk-3-bin", "packages_not_proved"),
        ("terminal", "terminal_not_selected"),
        ("browser", "default_browser_not_selected"),
        ("helper_file", "default_browser_not_selected"),
    ],
)
def test_provision_and_verify_xfce_default_apps(
    provisioner, monkeypatch, tmp_path, fault, reason
):
    calls = []

    def command(argv):
        calls.append(argv)
        output = ""
        if argv[0] == "dpkg-query":
            output = "\n".join(
                "not-installed" if package == fault else "installed"
                for package in argv[3:]
            )
        elif argv[0] == "passwd":
            output = "fixture P"
        return subprocess.CompletedProcess(argv, 0, stdout=output)

    monkeypatch.setattr(provisioner, "command", command)
    monkeypatch.setattr(provisioner, "wait_for_listener", lambda port: None)
    xrdp = tmp_path / "xrdp.ini"
    xrdp.write_text("[Globals]\nport=tcp://127.0.0.1:3389\n")
    real_path = provisioner.Path
    monkeypatch.setattr(
        provisioner, "Path",
        lambda name: xrdp if name == "/etc/xrdp/xrdp.ini" else real_path(name),
    )

    provisioner.provision(tmp_path, 3389, "project", "operator")
    packages = {"xfce4-helpers", "xdg-utils", "libgtk-3-bin"}
    assert packages.issubset(next(argv for argv in calls if "install" in argv))
    config = tmp_path / ".config/xfce4/helpers.rc"
    terminal = "TerminalEmulator=xfce4-terminal"
    browser = "WebBrowser=yoke-identity-browser"
    assert config.read_text().splitlines() == [terminal, browser]
    helper = tmp_path / ".local/share/xfce4/helpers/yoke-identity-browser.desktop"
    assert helper.read_text().splitlines() == [
        "[Desktop Entry]",
        "Type=X-XFCE-Helper",
        "Name=Yoke identity browser",
        "X-XFCE-Category=WebBrowser",
        "X-XFCE-Commands=gtk-launch -- yoke-identity-browser.desktop about:blank;",
        'X-XFCE-CommandsWithParameter=gtk-launch -- yoke-identity-browser.desktop "%s";',
    ]

    if fault == "terminal":
        config.write_text(browser + "\n")
    elif fault == "browser":
        config.write_text(terminal + "\n")
    elif fault == "helper_file":
        helper.unlink()

    if reason:
        with pytest.raises(provisioner.ProvisionFailure, match=reason):
            provisioner.verify(tmp_path)
    else:
        assert provisioner.verify(tmp_path)["ok"]
    assert packages.issubset(next(argv for argv in calls if argv[0] == "dpkg-query"))


@pytest.mark.posix_only(reason="runs on the remote Linux test machine")
def test_custom_desktop_session_is_preserved(provisioner, monkeypatch, tmp_path):
    monkeypatch.setattr(provisioner.platform, "system", lambda: "Linux")
    monkeypatch.setattr(provisioner, "posix_uid", lambda: 1001)
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
