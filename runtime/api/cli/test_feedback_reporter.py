"""Reporter email selection follows the authenticated actor, active harness and Git."""

import base64
import json
from types import SimpleNamespace
from unittest.mock import patch

from yoke_cli.feedback_reporter import git_email, harness_email, feedback_provenance


def test_authenticated_email_wins_without_reading_machine_login():
    response = SimpleNamespace(success=True, result={"actor_email": "actor@example.test", "universe_fingerprint": "fixture@2026-01-01T00:00:00Z"})
    with (patch("yoke_cli.feedback_reporter.ensure_handlers_loaded"),
          patch("yoke_cli.feedback_reporter.call_dispatcher", return_value=response),
          patch("yoke_cli.feedback_reporter.harness_email", side_effect=AssertionError("unneeded")),
          patch("yoke_cli.feedback_reporter.git_email", side_effect=AssertionError("unneeded"))):
        assert feedback_provenance()["reporter_email"] == "actor@example.test"


def test_only_active_harness_login_is_used(tmp_path, monkeypatch):
    (tmp_path / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "claude@example.test"}}))
    codex = tmp_path / ".codex"
    codex.mkdir()
    encoded = base64.urlsafe_b64encode(json.dumps({"email": "codex@example.test"}).encode()).decode().rstrip("=")
    (codex / "auth.json").write_text(json.dumps({"tokens": {"id_token": "header." + encoded + ".signature"}}))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    assert harness_email("claude-code", tmp_path) == "claude@example.test"
    assert harness_email("codex", tmp_path) == "codex@example.test"
    cursor = tmp_path / ".cursor"
    cursor.mkdir()
    (cursor / "cli-config.json").write_text(json.dumps({"authInfo": {"email": "cursor@example.test"}}))
    assert harness_email("cursor", tmp_path) == "cursor@example.test"
    assert harness_email(None, tmp_path) is None


def test_git_placeholder_is_not_a_reporter(tmp_path):
    with patch("yoke_cli.feedback_reporter.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="yoke@example.invalid\n")):
        assert git_email(tmp_path) is None
    with patch("yoke_cli.feedback_reporter.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="git@example.test\n")):
        assert git_email(tmp_path) == "git@example.test"
