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


def test_agent_refusal_carries_an_unsourced_vc_runtime(monkeypatch, capsys):
    monkeypatch.setattr(
        preflight,
        "collect_facts",
        lambda **kw: _ready_windows(vc_runtime=None, vc_runtime_missing=["msvcp140.dll"]),
    )
    parsed = Namespace(config_path=None, destination_local=True, agent=True)
    assert preflight.check_setup(parsed) is False
    out = capsys.readouterr().out
    assert '"state": "refused"' in out and "msvcp140.dll" in out


@pytest.mark.parametrize("mode", ["machine-only", "create-repo"])
def test_review_refuses_answer_chosen_local_without_a_vc_runtime_source(
    monkeypatch, tmp_path, mode
):
    """Local chosen by an answer reaches Review, which re-checks the runtime."""
    from types import SimpleNamespace

    from yoke_cli.config import onboard_preflight
    from yoke_contracts import windows_vc_runtime
    from yoke_contracts.embedded_postgres import engine_bin_dir

    seen = []

    def runtime_source(bin_dir, environ):
        seen.append(bin_dir)
        return None, ["msvcp140.dll"]

    monkeypatch.setattr(onboard_preflight.platform, "system", lambda: "Windows")
    monkeypatch.setattr(windows_vc_runtime, "runtime_source", runtime_source)
    monkeypatch.setattr(
        onboard_preflight.project_git_prerequisite, "git_available", lambda: True
    )
    result = SimpleNamespace(
        destination="local",
        project_mode=mode,
        project_checkout=None,
        config_path=str(tmp_path / "config.json"),
    )
    probes = onboard_preflight.PreflightProbes(
        vc_runtime_problem=onboard_preflight.windows_vc_runtime_problem
    )
    problems = onboard_preflight.preflight(result, probes=probes).problems
    assert problems == [windows_vc_runtime.unsourced_problem(["msvcp140.dll"])]
    assert seen == [engine_bin_dir(tmp_path)]
    assert onboard_preflight.default_probes().vc_runtime_problem is (
        onboard_preflight.windows_vc_runtime_problem
    )
    result.destination = "hosted"
    assert onboard_preflight.preflight(result, probes=probes).problems == []


STALE_APPLOCKER = {
    "policy": "AppLocker",
    "file": "%OSDRIVE%\\USERS\\QA\\APPDATA\\LOCAL\\PROGRAMS\\PYTHON\\PYTHON.EXE",
    "logged_at": "2026-11-27T21:14:05.1234567Z",
    "evidence": "Microsoft-Windows-AppLocker/EXE and DLL: enforced block event 8004, record 912",
}
UNRELATED_RECENT = {**STALE_APPLOCKER, "file": "C:\\Tools\\postgres-backup.exe", "logged_at": "2026-11-28T05:59:00Z"}
LOG_UNAVAILABLE = "wevtutil.exe exited 15007: The specified channel could not be found."


@pytest.mark.parametrize(
    "parsed",
    [
        Namespace(config_path=None, connect_url="https://upyoke.com", agent=True),
        Namespace(config_path=None, destination_local=True, agent=True),
    ],
)
def test_application_control_history_is_shown_but_never_refuses_setup(
    monkeypatch, capsys, parsed
):
    monkeypatch.delenv("YOKE_ONBOARD_DESTINATION", raising=False)
    monkeypatch.setattr(
        preflight,
        "collect_facts",
        lambda **kw: _ready_windows(
            vc_runtime="C:/Windows/System32/vcruntime140.dll",
            application_control_history=[STALE_APPLOCKER, UNRELATED_RECENT],
            probe_errors=[LOG_UNAVAILABLE],
        ),
    )
    assert preflight.check_setup(parsed) is True
    captured = capsys.readouterr()
    assert captured.out == ""  # no refusal envelope
    assert captured.err.count("warning (windows_application_control_history)") == 2
    assert "2026-11-27T21:14:05.1234567Z" in captured.err
    assert "record 912" in captured.err and "postgres-backup.exe" in captured.err
    assert "no per-app exception" in captured.err
    assert f"warning (windows_probe_incomplete): Preflight fact unavailable: {LOG_UNAVAILABLE}" in captured.err


def test_history_does_not_hide_another_blocking_preflight_result(monkeypatch, capsys):
    monkeypatch.setattr(
        preflight,
        "collect_facts",
        lambda **kw: _ready_windows(
            application_control_history=[STALE_APPLOCKER],
            invalid_names=["docs/aux.md"],
        ),
    )
    parsed = Namespace(config_path=None, connect_url="https://upyoke.com", agent=True)
    assert preflight.check_setup(parsed) is False
    out = capsys.readouterr().out
    assert '"state": "refused"' in out and "docs/aux.md" in out
    assert "Historical AppLocker" not in out


def test_status_keeps_application_control_history_visible(monkeypatch, tmp_path):
    from yoke_cli.config import status
    from yoke_contracts import windows_preflight_facts
    from yoke_contracts.windows_preflight import verdicts

    facts = _ready_windows(application_control_history=[STALE_APPLOCKER])
    monkeypatch.setattr(windows_preflight_facts, "collect_facts", lambda **kw: facts)
    monkeypatch.setattr(status, "attach_doctor", lambda result, **kw: result)
    result = status.build_status(
        config_path=tmp_path / "config.json", repo_root=tmp_path, check_reachability=False
    )
    assert result["native_preflight"]["application_control_history"] == [STALE_APPLOCKER]
    [row] = [r for r in verdicts(facts) if r["code"] == "windows_application_control_history"]
    assert row["severity"] == "warning" and STALE_APPLOCKER["logged_at"] in row["message"]
