"""Windows plan-limit credentials stay local and probes preserve their budget."""

import json
from types import SimpleNamespace

from yoke_harness import session_relay_plan_limits as limits
import pytest
pytestmark = pytest.mark.windows

def test_windows_claude_reads_user_credentials_without_keychain(tmp_path, monkeypatch):
    monkeypatch.setattr(limits.sys, "platform", "win32")
    monkeypatch.setattr(limits.Path, "home", lambda: tmp_path)
    credentials = tmp_path / ".claude" / ".credentials.json"
    credentials.parent.mkdir()
    credentials.write_text(json.dumps({"claudeAiOauth": {"accessToken": "local-token"}}))
    monkeypatch.setattr(limits.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no keychain")))
    assert limits._load_claude_credentials()["claudeAiOauth"]["accessToken"] == "local-token"


def test_windows_cursor_uses_roaming_profile_not_linux_config(tmp_path, monkeypatch):
    monkeypatch.setattr(limits.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "linux"))
    credentials = tmp_path / "roaming" / "cursor" / "auth.json"
    credentials.parent.mkdir(parents=True)
    credentials.write_text(json.dumps({"accessToken": "local-token"}))
    assert limits._cursor_access_token() == "local-token"
    credentials.write_text("broken JSON")
    assert limits._cursor_access_token() is None


def test_windows_claude_usage_sends_local_token_only_to_usage_probe(tmp_path, monkeypatch):
    monkeypatch.setattr(limits.sys, "platform", "win32")
    monkeypatch.setattr(limits, "_load_claude_credentials", lambda: {"claudeAiOauth": {"accessToken": "local-token"}})
    monkeypatch.setattr(limits, "probe_cli_surface", lambda *a, **k: SimpleNamespace(verdict="ok", version="2.3.4"))
    sent = []
    monkeypatch.setattr(limits, "plan_limit_http_json", lambda url, **kw: sent.append(kw) or "http_timeout")
    reading = limits.probe_claude_cli(observed_at="2026-11-16T12:00:00Z")
    assert sent[0]["headers"]["Authorization"] == "Bearer local-token"
    assert "local-token" not in repr(reading)
    assert "http_timeout" in repr(reading)
