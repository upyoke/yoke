"""Tests for ``lint_unmatched_path_glob``."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from yoke_core.domain import lint_unmatched_path_glob as lint
from yoke_core.hooks.types import Outcome


def _payload(
    command: str,
    *,
    cwd: str,
    working_directory: str | None = None,
    **extra: object,
) -> dict:
    tool_input: dict[str, object] = {"command": command}
    if working_directory is not None:
        tool_input["working_directory"] = working_directory
    payload = {
        "tool_name": "Bash",
        "tool_input": tool_input,
        "cwd": cwd,
        "session_id": "sess-test",
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }
    payload.update(extra)
    return payload


def _eval(
    command: str,
    *,
    cwd: str,
    working_directory: str | None = None,
    mode: str = "deny",
):
    with mock.patch.object(lint, "_read_mode", return_value=mode):
        return lint.evaluate_payload(
            _payload(command, cwd=cwd, working_directory=working_directory),
        )


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


def test_quoted_heredoc_markdown_link_is_allowed(tmp_path: Path) -> None:
    command = (
        "python3 - <<'PY'\n"
        'text = "[name](archive/decisions/name.md)"\n'
        "print(text)\n"
        "PY\n"
    )
    assert _eval(command, cwd=str(tmp_path)) is None


def test_unquoted_glob_on_heredoc_opener_line_is_still_denied(
    tmp_path: Path,
) -> None:
    command = "rg -n PATTERN docs/deploy* <<'EOF'\nbody\nEOF\n"
    result = _eval(command, cwd=str(tmp_path))
    assert result is not None
    assert "docs/deploy*" in result[1]


def test_matching_path_glob_is_allowed(tmp_path: Path) -> None:
    target = tmp_path / "docs"
    target.mkdir()
    (target / "deploy.md").write_text("ok\n", encoding="utf-8")
    assert _eval("ls docs/deploy*", cwd=str(tmp_path)) is None


def test_missing_cwd_does_not_deny() -> None:
    with mock.patch.object(lint, "_read_mode", return_value="deny"):
        assert (
            lint.evaluate_payload(
                _payload(
                    "rg -n PATTERN docs/deploy*",
                    cwd="",
                )
            )
            is None
        )


def test_evaluate_deny_decision_shape(tmp_path: Path) -> None:
    payload = _payload("rg -n PATTERN docs/deploy*", cwd=str(tmp_path))
    with (
        mock.patch.object(lint, "_read_mode", return_value="deny"),
        mock.patch.object(lint, "_emit_audit_event"),
    ):
        decision = lint.evaluate(lint._build_context_from_payload(payload))
    assert decision.outcome is Outcome.DENY
    assert decision.block is True


def _tree_with_deploy(path: Path) -> Path:
    docs = path / "docs"
    docs.mkdir(parents=True)
    (docs / "deploy.md").write_text("ok\n", encoding="utf-8")
    return path


def test_glob_is_resolved_against_working_directory_not_payload_cwd(
    tmp_path: Path,
) -> None:
    sticky = tmp_path / "sticky"
    sticky.mkdir()
    execution = _tree_with_deploy(tmp_path / "execution")
    assert (
        _eval(
            "ls docs/deploy*",
            cwd=str(sticky),
            working_directory=str(execution),
        )
        is None
    )


def test_denial_names_the_execution_tree_when_it_differs_from_payload_cwd(
    tmp_path: Path,
) -> None:
    payload_tree = _tree_with_deploy(tmp_path / "payload")
    execution = tmp_path / "execution"
    execution.mkdir()
    result = _eval(
        "ls docs/deploy*",
        cwd=str(payload_tree),
        working_directory=str(execution),
    )
    assert result is not None
    reason = result[1]
    assert "docs/deploy*" in reason
    assert str(execution) in reason
    assert "Checked tree:" in reason
    assert str(payload_tree) in reason
    assert "Payload cwd was" in reason
