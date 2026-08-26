"""Operator-machine privacy boundary coverage."""

from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess
import time
from unittest.mock import patch

import pytest

from yoke_contracts.hook_runner.hook_guard_catalog import GUARD_CATALOG
from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for
from yoke_contracts.hook_runner.local_privacy_guard import (
    classify_shell_command,
    classify_subprocess_args,
)
from yoke_core.domain import lint_local_privacy
from yoke_harness.hooks import local_policies, local_subset
from yoke_harness.hooks.deadline import HookDeadline
from yoke_harness.hooks.local_policy_common import DENY, NOOP


HOME = Path.home()
REPO = Path(__file__).resolve().parents[3]


def _quote(path: Path) -> str:
    return shlex.quote(str(path))


@pytest.mark.parametrize(
    ("command", "code"),
    [
        (f"find {_quote(HOME)} -maxdepth 6 -name codex", "home_root_scan"),
        ("find $HOME -maxdepth 4 -name python3", "home_root_scan"),
        ("ls $HOME/*", "home_root_glob"),
        ("cat ~/Documents/notes.txt", "protected_home_access"),
        ("rg token $HOME/Library/CloudStorage", "protected_home_access"),
        ("du -sh ~/Downloads", "protected_home_access"),
        (
            "cat '/Library/Application Support/com.apple.TCC/TCC.db'",
            "local_privacy_database",
        ),
        ("osascript -e 'tell app \"Finder\" to activate'", "local_gui_automation"),
        ("screencapture /tmp/screen.png", "local_gui_automation"),
        ("zsh -lc 'osascript -e beep'", "local_gui_automation"),
    ],
)
def test_classifier_denies_privacy_crossing_commands(command: str, code: str) -> None:
    violation = classify_shell_command(command, home=HOME, cwd=REPO)

    assert violation is not None
    assert violation.code == code
    assert "resolve_native_cli" in violation.reason()
    assert "repository/worktree" in violation.reason()


@pytest.mark.parametrize(
    "command",
    [
        f"find {_quote(REPO)} -maxdepth 4 -name codex",
        "find ~/.yoke -maxdepth 3 -name config.json",
        "rg -n local_privacy_guard packages runtime",
        "git status --short",
        "ssh test-mac 'osascript -e beep'",
    ],
)
def test_classifier_allows_scoped_or_remote_commands(command: str) -> None:
    assert classify_shell_command(command, home=HOME, cwd=REPO) is None


@pytest.mark.parametrize(
    "command", ["find . -name codex", "rg token", "grep -R token ."]
)
def test_relative_and_implicit_scans_are_denied_from_home(command: str) -> None:
    violation = classify_shell_command(command, home=HOME, cwd=HOME)

    assert violation is not None
    assert violation.code == "home_root_scan"


def test_relative_scan_is_allowed_from_repository() -> None:
    assert classify_shell_command("find . -name codex", home=HOME, cwd=REPO) is None


def test_subprocess_argv_and_shell_text_share_the_classifier() -> None:
    argv = ["zsh", "-lc", "screencapture /tmp/screen.png"]

    from_argv = classify_subprocess_args(argv, home=HOME, cwd=REPO)
    from_text = classify_subprocess_args(shlex.join(argv), home=HOME, cwd=REPO)

    assert from_argv == from_text
    assert from_argv is not None
    assert from_argv.service == "Screen Recording"


def test_repo_fixture_stops_local_automation_before_popen() -> None:
    with pytest.raises(pytest.fail.Exception, match="local privacy boundary"):
        subprocess.run(["osascript", "-e", "beep"], check=False)


def test_engine_and_product_local_policy_share_denial_text() -> None:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "cat ~/Desktop/operator.txt"},
        "cwd": str(REPO),
    }
    with patch.object(lint_local_privacy, "_read_mode", return_value="deny"):
        engine_verdict = lint_local_privacy.evaluate_payload(payload)
    product_verdict = local_policies.lint_local_privacy(payload)

    assert engine_verdict is not None
    assert engine_verdict[0] == "deny"
    assert product_verdict.outcome == DENY
    assert product_verdict.message in engine_verdict[1]


def test_engine_and_product_local_policy_share_safe_outcome() -> None:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": f"find {_quote(REPO)} -name codex"},
        "cwd": str(REPO),
    }

    assert lint_local_privacy.evaluate_payload(payload) is None
    assert local_policies.lint_local_privacy(payload).outcome == NOOP


def test_guard_is_protected_and_ordered_before_unmatched_globs() -> None:
    spec = next(spec for spec in GUARD_CATALOG if spec.guard == "lint_local_privacy")
    chain = ordered_pipeline_for("PreToolUse", "Bash")

    assert spec.protected is True
    assert spec.module == "yoke_core.domain.lint_local_privacy"
    assert chain.index(spec.module) < chain.index(
        "yoke_core.domain.lint_unmatched_path_glob"
    )


def test_product_local_subset_denies_before_https_relay() -> None:
    payload = json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "screencapture /tmp/screen.png"},
            "cwd": str(REPO),
        }
    )
    result = local_subset.evaluate_local_subset(
        "PreToolUse",
        payload,
        "codex",
        None,
        HookDeadline(budget_ms=3000, started_at=time.monotonic()),
        lint_config_snapshot={"lint_local_privacy": {"mode": "deny"}},
    )

    assert result.denied is True
    assert result.denial_audit is not None
    assert result.denial_audit["guard_key"] == ("yoke_core.domain.lint_local_privacy")
