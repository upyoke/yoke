"""Tests for ``lint_unmatched_path_glob``."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from yoke_core.domain import lint_unmatched_path_glob as lint
from yoke_core.hooks.types import Outcome


def _payload(command: str, *, cwd: str, **extra: object) -> dict:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": cwd,
        "session_id": "sess-test",
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }
    payload.update(extra)
    return payload


def _eval(command: str, *, cwd: str, mode: str = "deny"):
    with mock.patch.object(lint, "_read_mode", return_value=mode):
        return lint.evaluate_payload(_payload(command, cwd=cwd))


def test_unmatched_path_glob_denies_and_names_rg_files(tmp_path: Path) -> None:
    result = _eval("rg -n PATTERN docs/deploy*", cwd=str(tmp_path))
    assert result is not None
    mode, reason, outcome = result
    assert mode == "deny"
    assert outcome == "denied"
    assert "docs/deploy*" in reason
    assert "rg --files" in reason


def test_field_note_unquoted_test_glob_is_denied(tmp_path: Path) -> None:
    result = _eval(
        "rg -n relay runtime/api/cli/test_session_relay*",
        cwd=str(tmp_path),
    )
    assert result is not None
    assert "rg --files" in result[1]


def test_quoted_path_glob_is_allowed(tmp_path: Path) -> None:
    assert _eval("rg --glob 'docs/deploy*' PATTERN", cwd=str(tmp_path)) is None


def test_matching_path_glob_is_allowed(tmp_path: Path) -> None:
    target = tmp_path / "docs"
    target.mkdir()
    (target / "deploy.md").write_text("ok\n", encoding="utf-8")
    assert _eval("ls docs/deploy*", cwd=str(tmp_path)) is None


def test_missing_cwd_does_not_deny() -> None:
    with mock.patch.object(lint, "_read_mode", return_value="deny"):
        assert lint.evaluate_payload(_payload(
            "rg -n PATTERN docs/deploy*", cwd="",
        )) is None


def test_evaluate_deny_decision_shape(tmp_path: Path) -> None:
    payload = _payload("rg -n PATTERN docs/deploy*", cwd=str(tmp_path))
    with mock.patch.object(lint, "_read_mode", return_value="deny"), \
            mock.patch.object(lint, "_emit_audit_event"):
        decision = lint.evaluate(lint._build_context_from_payload(payload))
    assert decision.outcome is Outcome.DENY
    assert decision.block is True
