"""Read-shaped lane-guard regressions: classify reads as reads.

Covers the four proven false-deny shapes: cross-lane git/ls inspection
must still refuse but say read and name the main-checkout recipe;
``print`` / ``printf`` operands are not write targets; installed harness
surfaces are readable while a lane claim is held without gaining writes.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_lane_main_write, lint_session_cwd
from yoke_core.domain.lint_lane_main_write_classify import is_write_operation
from yoke_core.domain.lint_session_cwd_foreign_lane import (
    FAILURE_CLASS as FOREIGN_LANE_FAILURE_CLASS,
)
from yoke_core.domain.lint_session_cwd_read_only_signatures import (
    match_read_only_signature,
)
from yoke_core.domain.lint_session_cwd_path_authority import FREE_PATH_PREFIXES
from yoke_core.domain.lint_session_cwd_target_extract import (
    extract_command_targets,
    extract_payload_write_targets,
)


HOLDER = "sid-holder"
INTRUDER = "sid-intruder"
HELD_ITEM = 2220
INSTALLED_READ_TARGETS = (
    "~/.codex/plugins/cache/browser/SKILL.md",
    "~/.codex/skills/imagegen/SKILL.md",
    "~/.claude/plugins/marketplaces/browser/SKILL.md",
    "~/.codex/AGENTS.md",
    "~/.yoke/browser-runtime/chrome",
    "~/.local/bin/yoke",
    "~/.claude/settings.json",
)
EXCLUDED_READ_TARGETS = (
    "~/.yoke/secrets/capability-secrets/yoke/aws-admin/credentials",
    "~/.codex/auth.json",
    "~/.codex/config.toml",
    "~/.claude/skills/browser/SKILL.md",
)


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees").mkdir(parents=True)
    return repo_path


def _register(repo):
    register_machine_checkout(Path(repo).parent / "machine-config", Path(repo), 1)


def _seed_lane(conn, repo, *, session_id=HOLDER, item_id=HELD_ITEM):
    _register(repo)
    seed_item(conn, item_id=item_id, branch=f"YOK-{item_id}", repo_path=repo)
    seed_item_claim(conn, session_id, item_id=item_id)
    lane = repo / ".worktrees" / f"YOK-{item_id}"
    lane.mkdir(parents=True, exist_ok=True)
    return lane


class TestForeignLaneReadDenial:
    def test_git_show_stat_says_read_and_names_main_recipe(self, conn, repo):
        lane = _seed_lane(conn, repo)
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": INTRUDER,
            "tool_name": "Bash",
            "tool_input": {"command": f"git -C {lane} show HEAD --stat"},
        })
        assert verdict.allow is False
        assert verdict.failure_class == FOREIGN_LANE_FAILURE_CLASS
        assert "Refusing a read" in verdict.reason
        assert "Refusing a write" not in verdict.reason
        assert f"git -C {repo} show" in verdict.reason

    def test_ls_of_held_lane_says_read(self, conn, repo):
        lane = _seed_lane(conn, repo)
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": INTRUDER,
            "tool_name": "Bash",
            "tool_input": {"command": f"ls {lane}"},
        })
        assert verdict.allow is False
        assert "Refusing a read" in verdict.reason
        assert "Refusing a write" not in verdict.reason

    def test_write_into_held_lane_still_says_write(self, conn, repo):
        lane = _seed_lane(conn, repo)
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": INTRUDER,
            "tool_name": "Write",
            "tool_input": {"file_path": str(lane / "src" / "a.py")},
        })
        assert verdict.allow is False
        assert "Refusing a write" in verdict.reason
        assert "shared object store" not in verdict.reason


class TestPrintArgumentsAreNotWrites:
    def test_print_report_line_is_read_only(self):
        cmd = 'print "$_lines $_file"'
        assert match_read_only_signature(cmd) == "print-report"
        assert is_write_operation("Bash", {"tool_input": {"command": cmd}}) is False
        assert extract_command_targets(cmd) == []
        assert extract_payload_write_targets({"tool_input": {"command": cmd}}) == []

    def test_print_absolute_numeric_path_is_not_extracted(self):
        cmd = "print /Users/beebauman/yoke/350"
        assert extract_command_targets(cmd) == []
        assert extract_payload_write_targets({"tool_input": {"command": cmd}}) == []

    def test_compound_print_assignment_is_not_a_write(self):
        cmd = '_lines=350; _file=runtime/foo.py; print "$_lines $_file"'
        assert extract_command_targets(cmd) == []
        assert is_write_operation("Bash", {"tool_input": {"command": cmd}}) is False

    def test_echo_redirect_still_extracts_write_target(self):
        cmd = "echo hi > /tmp/yoke-print-out.txt"
        assert match_read_only_signature(cmd) is None
        assert extract_command_targets(cmd) == ["/tmp/yoke-print-out.txt"]

    def test_print_from_lane_does_not_arm_main_write(self, conn, repo):
        _seed_lane(conn, repo, session_id="sid-lane")
        verdict = lint_lane_main_write.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Bash",
            "cwd": str(repo),
            "tool_input": {"command": 'print "$_lines $_file"'},
        })
        assert verdict.allow is True


class TestSanctionedReadPaths:
    def test_attachment_and_config_prefixes_are_registered(self):
        assert "~/.codex/attachments" in FREE_PATH_PREFIXES
        assert "~/.yoke/config.json" in FREE_PATH_PREFIXES

    def test_codex_attachment_read_allowed_with_lane_claim(self, conn, repo):
        _seed_lane(conn, repo, session_id="sid-lane")
        target = os.path.join(os.path.expanduser("~"), ".codex", "attachments", "task.md")
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Read",
            "tool_input": {"file_path": target},
        })
        assert verdict.allow is True

    def test_sed_of_codex_attachment_allowed_with_lane_claim(self, conn, repo):
        _seed_lane(conn, repo, session_id="sid-lane")
        target = os.path.expanduser("~/.codex/attachments/note.txt")
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Bash",
            "tool_input": {"command": f"sed -n '1,20p' {target}"},
        })
        assert verdict.allow is True

    def test_machine_config_read_allowed_with_lane_claim(self, conn, repo):
        _seed_lane(conn, repo, session_id="sid-lane")
        target = os.path.join(os.path.expanduser("~"), ".yoke", "config.json")
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Read",
            "tool_input": {"file_path": target},
        })
        assert verdict.allow is True

    def test_machine_secrets_still_denied_with_lane_claim(self, conn, repo):
        _seed_lane(conn, repo, session_id="sid-lane")
        target = os.path.join(
            os.path.expanduser("~"),
            ".yoke",
            "secrets",
            "capability-secrets",
            "yoke",
        )
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Read",
            "tool_input": {"file_path": target},
        })
        assert verdict.allow is False

    @pytest.mark.parametrize("target", INSTALLED_READ_TARGETS)
    def test_installed_harness_path_read_allowed_with_lane_claim(
        self, conn, repo, target,
    ):
        _seed_lane(conn, repo, session_id="sid-lane")
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Read",
            "tool_input": {"file_path": os.path.expanduser(target)},
        })
        assert verdict.allow is True

    def test_installed_plugin_shell_read_allowed_with_lane_claim(self, conn, repo):
        _seed_lane(conn, repo, session_id="sid-lane")
        target = os.path.expanduser(INSTALLED_READ_TARGETS[0])
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Bash",
            "tool_input": {"command": f"sed -n '1,20p' {target}"},
        })
        assert verdict.allow is True

    def test_xdg_installed_launcher_read_allowed_with_lane_claim(
        self, conn, repo, tmp_path, monkeypatch,
    ):
        _seed_lane(conn, repo, session_id="sid-lane")
        launcher = tmp_path / "xdg-bin" / "yoke"
        monkeypatch.setenv("XDG_BIN_HOME", str(launcher.parent))
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Read",
            "tool_input": {"file_path": str(launcher)},
        })
        assert verdict.allow is True

    @pytest.mark.parametrize("target", INSTALLED_READ_TARGETS)
    def test_installed_harness_path_write_still_denied_with_lane_claim(
        self, conn, repo, target,
    ):
        _seed_lane(conn, repo, session_id="sid-lane")
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Write",
            "tool_input": {"file_path": os.path.expanduser(target)},
        })
        assert verdict.allow is False

    @pytest.mark.parametrize("target", EXCLUDED_READ_TARGETS)
    def test_sensitive_or_uninstalled_harness_path_read_still_denied(
        self, conn, repo, target,
    ):
        _seed_lane(conn, repo, session_id="sid-lane")
        verdict = lint_session_cwd.evaluate_pre_tool_use({
            "session_id": "sid-lane",
            "tool_name": "Read",
            "tool_input": {"file_path": os.path.expanduser(target)},
        })
        assert verdict.allow is False
