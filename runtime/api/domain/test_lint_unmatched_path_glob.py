"""Tests for ``lint_unmatched_path_glob``."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from yoke_core.domain import lint_unmatched_path_glob as lint
from yoke_core.hooks.types import Outcome


def _payload(
    command: str,
    *,
    cwd: str,
    working_directory: str | None = None,
    **extra: object,
) -> dict:
    tool_input: dict[str, object] = {"command": command, "shell": "/bin/zsh"}
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
    assert "rg -n PATTERN docs --glob 'deploy*'" in reason


def test_glob_denial_lists_bounded_stem_matches(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "deploy-guide.md").write_text("ok\n", encoding="utf-8")
    reason = _eval("rg PAT docs/deploy*.py", cwd=str(tmp_path))[1]
    assert "docs/deploy-guide.md" in reason
    assert "git ls-files" in reason


def test_ripgrep_replace_flag_refused_with_search_repair(tmp_path: Path) -> None:
    result = _eval("rg -rn PAT docs", cwd=str(tmp_path))
    assert result is not None
    assert "rg -n PAT docs" in result[1]
    assert "lint-ripgrep-replace" in result[1]


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


@pytest.mark.parametrize(
    "default, explicit, denied",
    [
        ("/bin/zsh", "/bin/bash", False),
        ("/bin/bash", "/bin/zsh", True),
        ("/bin/bash", None, False),
        ("/bin/zsh", None, True),
        ("", None, False),
    ],
)
def test_glob_guard_uses_command_shell_on_both_hook_paths(
    monkeypatch,
    tmp_path,
    default,
    explicit,
    denied,
):
    from yoke_harness.hooks.unmatched_path_glob import lint_unmatched_path_glob
    from yoke_harness.hooks.local_policy_common import DENY

    monkeypatch.setenv("SHELL", default)
    payload = _payload("ls missing/*", cwd=str(tmp_path))
    payload["tool_input"].pop("shell")
    if explicit is not None:
        payload["tool_input"]["shell"] = explicit
    with mock.patch.object(lint, "_read_mode", return_value="deny"):
        assert (lint.evaluate_payload(payload) is not None) is denied
    assert (lint_unmatched_path_glob(payload).outcome == DENY) is denied


@pytest.mark.parametrize("hook", ["core", "client"])
@pytest.mark.parametrize("operand", ["home", "absolute", "relative"])
@pytest.mark.parametrize("matching", [True, False])
def test_path_globs_use_the_executing_filesystem(
    tmp_path: Path, monkeypatch, hook: str, operand: str, matching: bool
) -> None:
    from yoke_harness.hooks.local_policy_common import DENY
    from yoke_harness.hooks.unmatched_path_glob import lint_unmatched_path_glob

    home = tmp_path / "home"
    downloads = home / "Downloads"
    downloads.mkdir(parents=True)
    (downloads / "Meeting-notes.txt").write_text("notes")
    monkeypatch.setenv("HOME", str(home))
    cwd = tmp_path / "repository"
    cwd.mkdir()
    stem = "Meeting" if matching else "Missing"
    if operand == "home":
        token = f"~/Downloads/{stem}*"
    elif operand == "absolute":
        token = str(downloads / f"{stem}*")
    else:
        token = f"../home/Downloads/{stem}*"
    payload = _payload(f"ls {token}", cwd=str(cwd))
    if hook == "core":
        with mock.patch.object(lint, "_read_mode", return_value="deny"):
            result = lint.evaluate_payload(payload)
        denied = result is not None
        reason = result[1] if result else ""
    else:
        result = lint_unmatched_path_glob(payload)
        denied = result.outcome == DENY
        reason = result.message
    assert denied is not matching
    if denied:
        assert token in reason
        assert "Checked pattern:" in reason
        assert "rg --files" in reason


@pytest.mark.parametrize("hook", ["core", "client"])
def test_home_glob_does_not_match_a_literal_tilde_directory(
    tmp_path: Path, monkeypatch, hook: str
) -> None:
    from yoke_harness.hooks.local_policy_common import DENY
    from yoke_harness.hooks.unmatched_path_glob import lint_unmatched_path_glob

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    literal = tmp_path / "repository" / "~" / "Downloads"
    literal.mkdir(parents=True)
    (literal / "Meeting-notes.txt").write_text("notes")
    cwd = str(tmp_path / "repository")
    if hook == "core":
        assert _eval("ls ~/Downloads/Meeting*", cwd=cwd) is not None
    else:
        assert (
            lint_unmatched_path_glob(
                _payload("ls ~/Downloads/Meeting*", cwd=cwd)
            ).outcome
            == DENY
        )


def test_home_glob_repair_enumerates_expanded_parent(tmp_path: Path, monkeypatch):
    home = tmp_path / "home with spaces"
    downloads = home / "Downloads"
    downloads.mkdir(parents=True)
    notes = downloads / "Meeting-notes.txt"
    notes.write_text("notes")
    monkeypatch.setenv("HOME", str(home))
    cwd = tmp_path / "repository"
    cwd.mkdir()
    reason = _eval("ls ~/Downloads/Meeting*.pdf", cwd=str(cwd))[1]
    assert str(notes) in reason
    assert f"'{downloads}'" in reason
    assert "Checked pattern:" in reason


def test_cd_and_unexpanded_globs_follow_the_segment_base(tmp_path: Path) -> None:
    from yoke_harness.hooks.local_policy_common import DENY
    from yoke_harness.hooks.unmatched_path_glob import lint_unmatched_path_glob

    other = tmp_path / "other"
    (other / "infra").mkdir(parents=True)
    (other / "infra" / "Pulumi.prod.yaml").write_text("x\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "deploy.md").write_text("ok\n", encoding="utf-8")
    checked = str(other.resolve())
    cases = [
        (f"cd {other} && ls infra/Pulumi*.yaml*", True, ""),
        (f"cd {other} && ls nomatch/*", False, checked),
        (f"cd {other} && ls docs/deploy*", False, checked),
        ("S=/x; wc -l $S/*.md", True, ""),
        ("wc -l ${S}/*.md", True, ""),
        ("cd $D && ls a/*", True, ""),
        ("wc -l `pwd`/*.md", True, ""),
        ("rg -n PATTERN docs/missing* 2>/dev/null", False, "2>/dev/null"),
        ("rg -n PATTERN docs/missing* >out.txt", False, ">out.txt"),
        ("rg -n PATTERN docs/missing* <in.txt", False, "<in.txt"),
    ]
    for command, allowed, marker in cases:
        for hook in ("core", "client"):
            if hook == "core":
                result = _eval(command, cwd=str(tmp_path))
                denied = result is not None
                reason = result[1] if result else ""
            else:
                verdict = lint_unmatched_path_glob(_payload(command, cwd=str(tmp_path)))
                denied = verdict.outcome == DENY
                reason = verdict.message
            assert denied is not allowed, command
            if marker:
                assert marker in reason, command
                assert f"'{marker}'" not in reason, command
