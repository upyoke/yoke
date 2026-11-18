"""Linux desktop provisioning selects XFCE defaults and confines RDP to the tailnet."""

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.fixture
def provisioner(monkeypatch):
    scripts = (
        Path(__file__).resolve().parents[3]
        / "packages/yoke-harness/src/yoke_harness/host_provisioning"
    )
    # The provisioner imports its sibling the way it runs on the host.
    for name in ("linux_desktop_listener", "provision_linux_desktop"):
        spec = importlib.util.spec_from_file_location(name, scripts / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
    return module


def test_service_socket_startup_is_waited_for(provisioner, monkeypatch):
    outputs = iter(["", "LISTEN 0 2 0.0.0.0:3389 0.0.0.0:*"])
    monkeypatch.setattr(
        provisioner,
        "command",
        lambda argv: subprocess.CompletedProcess(argv, 0, stdout=next(outputs)),
    )
    monkeypatch.setattr(provisioner.time, "sleep", lambda seconds: None)
    provisioner.wait_for_listener(3389, provisioner.ANY_ADDRESS)


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
        elif argv[-1] == "ruleset":
            output = sys.modules["linux_desktop_listener"].firewall_rules(3389)
        return subprocess.CompletedProcess(argv, 0, stdout=output)

    monkeypatch.setattr(provisioner, "command", command)
    monkeypatch.setattr(provisioner, "wait_for_listener", lambda port, address: None)
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
