"""Plan-limit probes read local credentials without calling macOS tools on Linux."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_harness import session_relay_plan_limits as limits

NOW = "2026-09-01T00:00:00Z"


@pytest.fixture
def linux_home(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(limits.sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    def unexpected_tool(*args, **kwargs):
        pytest.fail("Linux credentials must not invoke the macOS keychain")

    monkeypatch.setattr(limits.subprocess, "run", unexpected_tool)
    return tmp_path


@pytest.mark.parametrize("xdg", [None, "", "custom-config"])
def test_linux_cursor_file_token_reaches_usage_probe(monkeypatch, linux_home, xdg):
    root = linux_home / (xdg or ".config")
    if xdg is not None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(root) if xdg else "")
    path = root / "cursor/auth.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"accessToken": "fixture-token"}))
    calls = []

    def http(url, **kwargs):
        calls.append(kwargs["headers"]["Authorization"])
        if url.endswith("GetPlanInfo"):
            return {"planInfo": {"planName": "Ultra"}}
        return {"planUsage": {"autoPercentUsed": 10, "apiPercentUsed": 20}}

    monkeypatch.setattr(limits, "plan_limit_http_json", http)
    reading = limits.probe_cursor_cli(observed_at=NOW)
    assert calls == ["Bearer fixture-token", "Bearer fixture-token"]
    assert reading["plan_tier"] == "Ultra"
    assert [w["remaining_percent"] for w in reading["windows"]] == [90, 80]
    assert "fixture-token" not in repr(reading)


@pytest.mark.parametrize(
    "raw", [None, "not-json", "[]", "{}", '{"accessToken": 12}', '{"accessToken": " "}']
)
def test_linux_cursor_unreadable_credentials_are_named_stale(linux_home, raw):
    path = linux_home / ".config/cursor/auth.json"
    path.parent.mkdir(parents=True)
    if raw is not None:
        path.write_text(raw)
    reading = limits.probe_cursor_cli(observed_at=NOW)
    assert reading["windows"][0]["reason"] == "stale_credential"


def _claude_version(monkeypatch, verdict="ok", version="2.3.4"):
    probed = []

    def probe(surface, command):
        probed.append((surface, command))
        return SimpleNamespace(
            verdict=verdict,
            version=version,
            error=None if verdict == "ok" else "executable 'claude' was not found",
        )

    monkeypatch.setattr(limits, "probe_cli_surface", probe)
    return probed


def _claude_file_credentials(linux_home):
    path = linux_home / ".claude/.credentials.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "fixture-token"}}))


def test_linux_claude_uses_file_credentials_without_keychain(monkeypatch, linux_home):
    _claude_file_credentials(linux_home)
    _claude_version(monkeypatch)
    calls = []

    def http(url, **kwargs):
        calls.append(kwargs["headers"]["Authorization"])
        return {"limits": [{"kind": "session", "percent": 25}]}

    monkeypatch.setattr(limits, "plan_limit_http_json", http)
    reading = limits.probe_claude_cli(observed_at=NOW)
    assert calls == ["Bearer fixture-token"]
    assert reading["windows"][0]["remaining_percent"] == 75
    assert "fixture-token" not in repr(reading)


def test_claude_usage_check_identifies_as_installed_claude_code(
    monkeypatch, linux_home
):
    _claude_file_credentials(linux_home)
    probed = _claude_version(monkeypatch, version="2.3.4")
    sent = []

    def http(url, **kwargs):
        sent.append(kwargs["headers"])
        return {"limits": [{"kind": "session", "percent": 25}]}

    monkeypatch.setattr(limits, "plan_limit_http_json", http)
    limits.probe_claude_cli(observed_at=NOW)
    assert probed == [("claude-cli", limits.CLI_SURFACE_PROBES["claude-cli"])]
    assert sent == [
        {
            "Authorization": "Bearer fixture-token",
            "User-Agent": "claude-code/2.3.4",
            "anthropic-beta": "oauth-2025-04-20",
        }
    ]


def test_claude_unreadable_version_is_named_and_skips_usage_check(
    monkeypatch, linux_home
):
    _claude_file_credentials(linux_home)
    _claude_version(monkeypatch, verdict="missing", version=None)

    def http(url, **kwargs):
        pytest.fail("an unidentified usage check must not be sent")

    monkeypatch.setattr(limits, "plan_limit_http_json", http)
    reading = limits.probe_claude_cli(observed_at=NOW)
    assert reading["windows"][0]["reason"] == "claude_version_unreadable_missing"


def test_macos_cursor_keeps_keychain_source(monkeypatch):
    monkeypatch.setattr(limits.sys, "platform", "darwin")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="fixture-token\n")

    monkeypatch.setattr(limits.subprocess, "run", run)
    assert limits._cursor_access_token() == "fixture-token"
    assert calls == [
        ["security", "find-generic-password", "-s", "cursor-access-token", "-w"]
    ]


def test_macos_claude_falls_back_to_credentials_file(monkeypatch, linux_home):
    monkeypatch.setattr(limits.sys, "platform", "darwin")
    monkeypatch.setattr(
        limits.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1)
    )
    path = linux_home / ".claude/.credentials.json"
    path.parent.mkdir()
    path.write_text('{"claudeAiOauth": {"accessToken": "fixture-token"}}')
    assert (
        limits._load_claude_credentials()["claudeAiOauth"]["accessToken"]
        == "fixture-token"
    )
