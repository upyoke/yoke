"""Setup refuses Windows hazards before the answer store or prepare writes."""

from __future__ import annotations

from argparse import Namespace

import pytest

from yoke_cli.config import onboard_native_preflight as preflight


pytestmark = pytest.mark.windows


def test_setup_refuses_before_selecting_shell(monkeypatch, capsys):
    from yoke_cli.commands.adapters import onboard

    monkeypatch.setattr(
        preflight,
        "collect_facts",
        lambda **kw: {
            "system": "Windows",
            "build": 9600,
            "edition": "Windows 8",
            "arch": "x86",
        },
    )
    monkeypatch.setattr(
        onboard.onboard_agent,
        "select_shell",
        lambda parsed: (_ for _ in ()).throw(
            AssertionError("must not select a shell or open an answer store")
        ),
    )
    assert onboard.onboard(["--agent"]) == 2
    captured = capsys.readouterr()
    assert "windows_version" in captured.err
    assert '"state": "refused"' in captured.out
    assert "WSL is blocked" in captured.err


def _ready_windows(**overrides):
    return {
        "system": "Windows",
        "build": 26100,
        "edition": "Windows 11 Pro",
        "arch": "AMD64",
        "git": "git.exe",
        "ssh": "ssh.exe",
        "long_paths_enabled": True,
        "desktop": True,
        "browser": True,
        **overrides,
    }


@pytest.mark.parametrize(
    "parsed,proceeds",
    [
        (Namespace(config_path=None, destination_local=True), False),
        (Namespace(config_path=None, connect_url="https://upyoke.com"), True),
    ],
)
def test_missing_vc_runtime_stops_local_setup_only(monkeypatch, capsys, parsed, proceeds):
    monkeypatch.delenv("YOKE_ONBOARD_DESTINATION", raising=False)
    monkeypatch.setattr(
        preflight, "collect_facts", lambda **kw: _ready_windows(vc_runtime=None)
    )
    assert preflight.check_setup(parsed) is proceeds
    err = capsys.readouterr().err
    assert ("error" if not proceeds else "warning") + " (windows_vc_runtime)" in err
    assert "winget install --id Microsoft.VCRedist.2015+.x64 -e" in err


def test_present_vc_runtime_lets_local_setup_proceed(monkeypatch, capsys):
    monkeypatch.setattr(
        preflight,
        "collect_facts",
        lambda **kw: _ready_windows(vc_runtime="C:/Windows/System32/vcruntime140.dll"),
    )
    assert preflight.check_setup(Namespace(config_path=None, destination_local=True))
    assert "info (windows_vc_runtime)" in capsys.readouterr().err


def test_other_os_preflight_prints_nothing(monkeypatch, capsys):
    monkeypatch.setattr(preflight, "collect_facts", lambda **kw: {"system": "Darwin"})
    assert preflight.check_setup(Namespace(config_path=None))
    assert capsys.readouterr() == ("", "")


def test_agent_guidance_teaches_native_windows_and_wsl_blocked(monkeypatch):
    from yoke_cli.config import setup_agent_response as response
    from yoke_cli.config.setup_prompt import SetupPrompt

    from types import SimpleNamespace

    monkeypatch.setattr(response, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(response, "yoke_executable", lambda: "yoke.exe")
    prompt = SetupPrompt(step="account", key="destination", title="Where?")
    assert "WSL is blocked" in response.question_fields(prompt)["guidance"]


def test_status_collects_preflight_without_doctor(monkeypatch, tmp_path):
    from yoke_cli.config import status
    from yoke_contracts import windows_preflight_facts

    monkeypatch.setattr(
        windows_preflight_facts,
        "collect_facts",
        lambda **kw: {
            "system": "Windows",
            "build": 9600,
            "edition": "Windows 8",
            "arch": "x86",
        },
    )
    monkeypatch.setattr(status, "attach_doctor", lambda result, **kw: result)
    result = status.build_status(
        config_path=tmp_path / "config.json",
        repo_root=tmp_path,
        check_reachability=False,
    )
    assert any(r["code"] == "windows_version" for r in result["issues"])
    assert result["native_preflight"]["system"] == "Windows"
