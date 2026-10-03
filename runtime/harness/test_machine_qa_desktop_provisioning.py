"""Pack desktop routes retain loopback safety and distinguish setup from UI proof."""

import importlib.util
import io
import json
from pathlib import Path
import sys

import pytest


@pytest.fixture
def provisioners(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "packs/machine-qa/pack.json").read_text())
    version = manifest["versions"][manifest["latest_version"]]
    scripts = root / "packs/machine-qa" / version["source"] / "ops/machine-qa"
    loaded = []
    for name in ("provision_linux_desktop", "provision_windows_wsl_desktop"):
        spec = importlib.util.spec_from_file_location(name, scripts / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        loaded.append(module)
    return loaded


def test_listener_configuration_preserves_other_sections(provisioners):
    linux, _ = provisioners
    port = linux.DEFAULT_RDP_PORT + 1
    content = "[Globals]\nport=3389\n[session]\nport=-1\n"
    assert linux.localhost_config(content, port) == (
        f"[Globals]\nport=tcp://127.0.0.1:{port}\n[session]\nport=-1\n"
    )
    linux.prove_listener(f"LISTEN 0 2 127.0.0.1:{port} 0.0.0.0:*", port)


@pytest.mark.parametrize("address", ["0.0.0.0", "[::]", "127.0.0.2"])
def test_non_loopback_desktop_listener_is_refused(provisioners, address):
    linux, _ = provisioners
    port = linux.DEFAULT_RDP_PORT
    with pytest.raises(linux.ProvisionFailure, match="loopback_not_proved"):
        linux.prove_listener(f"LISTEN 0 2 {address}:{port} 0.0.0.0:*", port)


@pytest.mark.parametrize("verify", [False, True])
def test_wsl_route_reuses_linux_provisioner_and_keeps_ui_unproved(
    provisioners, monkeypatch, capsys, verify
):
    linux, windows = provisioners
    home = Path("/home/tester")
    calls = []
    monkeypatch.setattr(
        windows, "windows_facts", lambda: {"windows": {"Caption": "Server"}}
    )
    monkeypatch.setattr(linux, "prerequisites", lambda: home)
    monkeypatch.setattr(
        linux, "provision", lambda *args: calls.append(("provision", *args))
    )
    monkeypatch.setattr(linux, "verify", lambda *args: {"ok": True})
    monkeypatch.setattr(linux, "desktop_password_input", lambda: "fixture-secret")
    monkeypatch.setattr(
        linux,
        "set_desktop_password",
        lambda password: calls.append(("password", password)),
    )
    monkeypatch.setattr(
        windows,
        "prove_windows_localhost",
        lambda port: calls.append(("localhost", port)),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["provisioner", "--verify" if verify else "--desktop-password-stdin"],
    )
    assert windows.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["headed_application_proved"] is False
    assert result["desktop_session"] == "not_started"
    assert "fixture-secret" not in json.dumps(result)
    assert calls == [
        *([] if verify else [("provision", home, windows.DEFAULT_WSL_RDP_PORT)]),
        ("localhost", windows.DEFAULT_WSL_RDP_PORT),
        *([] if verify else [("password", "fixture-secret")]),
    ]


@pytest.mark.parametrize("input_text", ["", "line\nline", "line\r", "x" * 1025])
def test_desktop_password_input_refuses_invalid_private_input(
    provisioners, monkeypatch, input_text
):
    linux, _ = provisioners
    monkeypatch.setattr(sys, "stdin", io.StringIO(input_text))
    with pytest.raises(linux.ProvisionFailure, match="desktop_password_input_invalid"):
        linux.desktop_password_input()


def test_desktop_password_input_refuses_personal_terminal_prompt(
    provisioners, monkeypatch
):
    linux, _ = provisioners
    monkeypatch.setattr(
        sys, "stdin", type("Terminal", (), {"isatty": lambda self: True})()
    )
    with pytest.raises(linux.ProvisionFailure, match="desktop_password_input_required"):
        linux.desktop_password_input()


def test_desktop_fixture_password_stays_on_stdin(provisioners, monkeypatch):
    import pwd

    linux, _ = provisioners
    password = "private-fixture-secret"
    calls = []
    monkeypatch.setattr(
        pwd, "getpwuid", lambda uid: type("User", (), {"pw_name": "tester"})()
    )
    monkeypatch.setattr(
        linux,
        "command",
        lambda argv, **kwargs: calls.append((argv, kwargs)),
    )

    linux.set_desktop_password(password)
    assert calls == [
        (["sudo", "-n", "chpasswd"], {"input_text": f"tester:{password}\n"})
    ]


@pytest.mark.parametrize("index", [0, 1])
def test_verify_refuses_secret_flag_before_any_host_action(
    provisioners, monkeypatch, index
):
    module = provisioners[index]
    monkeypatch.setattr(
        sys, "argv", ["provisioner", "--verify", "--desktop-password-stdin"]
    )
    monkeypatch.setattr(
        provisioners[0], "desktop_password_input", lambda: pytest.fail("read secret")
    )
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2


def test_wsl_forwarding_failure_has_no_public_listener_fallback(
    provisioners, monkeypatch
):
    linux, windows = provisioners

    def fail(argv):
        raise linux.ProvisionFailure("command failed")

    monkeypatch.setattr(linux, "command", fail)
    with pytest.raises(
        linux.ProvisionFailure, match="windows_wsl_localhost_unavailable"
    ):
        windows.prove_windows_localhost(windows.DEFAULT_WSL_RDP_PORT)


def test_wsl_provisioning_refuses_non_wsl_before_host_mutation(
    provisioners, monkeypatch
):
    linux, windows = provisioners
    monkeypatch.setattr(windows.platform, "release", lambda: "native-linux")
    with pytest.raises(linux.ProvisionFailure, match="windows_wsl_required"):
        windows.windows_facts()
