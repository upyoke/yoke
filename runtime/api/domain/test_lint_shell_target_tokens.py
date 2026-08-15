"""Tests for :mod:`lint_shell_target_tokens` and its two consumers.

The capture-first recipe in the repo's command-output rule redirects
through a variable assigned from ``mktemp``. Both target extractors and
the lane-main-write guard have to agree that the redirect lands in the
temp root rather than under the harness cwd, so the extractor units and
the end-to-end guard verdict live together here.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_lane_main_write
from yoke_core.domain.lint_session_cwd_target_extract import (
    analyze_payload_write_targets,
    extract_command_targets,
    extract_payload_write_targets,
)
from yoke_core.domain.lint_shell_target_tokens import (
    expand_variables,
    path_target_from_token,
    shell_variable_bindings,
)


CAPTURE_TEMPLATE = "/tmp/yoke-cmd.XXXXXX"


def _capture_first(command: str, template: str = CAPTURE_TEMPLATE) -> str:
    """The documented capture-first block wrapped around ``command``."""
    return (
        f"_tmp=$(mktemp {template})\n"
        f'{command} >"$_tmp" 2>&1; _rc=$?\n'
        'tail -80 "$_tmp"\n'
        'grep -E "FAIL|ERROR|error" "$_tmp" || true\n'
        'exit "$_rc"\n'
    )


def _bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestVariableBindings:
    def test_absolute_mktemp_template_binds_that_path(self):
        bindings = shell_variable_bindings(f"_tmp=$(mktemp {CAPTURE_TEMPLATE})")
        assert bindings["_tmp"] == CAPTURE_TEMPLATE

    def test_temp_root_flag_binds_under_the_os_temp_root(self):
        bindings = shell_variable_bindings("_raw=$(mktemp -t yoke-cmd.XXXXXX)")
        assert bindings["_raw"] == os.path.join(
            tempfile.gettempdir(), "yoke-cmd.XXXXXX"
        )

    def test_explicit_tmpdir_flag_wins_over_the_os_temp_root(self):
        bindings = shell_variable_bindings("_d=$(mktemp -d -p /var/spool x.XXXXXX)")
        assert bindings["_d"] == os.path.join("/var/spool", "x.XXXXXX")

    def test_bare_mktemp_binds_under_the_os_temp_root(self):
        bindings = shell_variable_bindings("_t=$(mktemp)")
        assert Path(bindings["_t"]).parent == Path(tempfile.gettempdir())

    def test_relative_template_without_a_root_flag_stays_relative(self):
        """``mktemp notes.XXXXXX`` creates in the working directory, so the
        binding stays relative and the caller resolves it against its cwd.
        """
        assert shell_variable_bindings("_t=$(mktemp notes.XXXXXX)")["_t"] == (
            "notes.XXXXXX"
        )

    def test_backtick_substitution_binds_too(self):
        bindings = shell_variable_bindings(f"_t=`mktemp {CAPTURE_TEMPLATE}`")
        assert bindings["_t"] == CAPTURE_TEMPLATE

    def test_literal_assignment_binds_its_value(self):
        assert shell_variable_bindings('out="/tmp/notes.log"')["out"] == (
            "/tmp/notes.log"
        )

    def test_non_mktemp_substitution_binds_nothing(self):
        bindings = shell_variable_bindings("_t=$(date +%s)")
        assert "_t" not in bindings
        assert expand_variables("$_t", bindings) is None

    def test_exit_status_capture_stays_unresolvable(self):
        bindings = shell_variable_bindings("_rc=$?")
        assert expand_variables("$_rc", bindings) is None
        assert expand_variables("${PIPESTATUS[0]}", bindings) is None

    def test_reassignment_to_an_opaque_value_drops_the_binding(self):
        command = f"_t=$(mktemp {CAPTURE_TEMPLATE})\n_t=$(date)\ncat > \"$_t\""
        assert "_t" not in shell_variable_bindings(command)

    def test_braced_reference_and_suffix_expand(self):
        bindings = {"root": "/tmp/run"}
        assert expand_variables("${root}/out.log", bindings) == "/tmp/run/out.log"
        assert expand_variables("$root.log", bindings) == "/tmp/run.log"

    def test_unbound_reference_is_no_verdict_not_a_relative_path(self):
        assert expand_variables('$CAPTURE', {}) is None
        assert path_target_from_token("$CAPTURE", {}) is None


class TestCaptureFirstWriteTargets:
    def test_capture_redirect_resolves_to_the_temp_root(self):
        payload = _bash(_capture_first("ruff check runtime"))
        assert extract_payload_write_targets(payload) == [CAPTURE_TEMPLATE]

    def test_lane_git_commit_capture_names_only_lane_and_temp_paths(self):
        """The shape the capture-first rule pairs with ``git -C <worktree>``:
        neither operand may resolve under the main checkout.
        """
        lane = "/Users/dev/yoke/.worktrees/YOK-1"
        payload = _bash(_capture_first(f'git -C {lane} commit -m "msg"'))
        assert extract_payload_write_targets(payload) == [CAPTURE_TEMPLATE, lane]

    def test_os_temp_root_capture_resolves_there_too(self):
        payload = _bash(_capture_first("pytest -q", template="-t yoke-cmd.XXXXXX"))
        assert extract_payload_write_targets(payload) == [
            os.path.join(tempfile.gettempdir(), "yoke-cmd.XXXXXX")
        ]

    def test_unresolvable_capture_variable_yields_no_target(self):
        analysis = analyze_payload_write_targets(_bash('pytest -q > "$CAPTURE"'))
        assert analysis.targets == []
        assert analysis.unresolved_variable is True

    def test_resolved_capture_reports_nothing_unresolved(self):
        analysis = analyze_payload_write_targets(_bash(_capture_first("pytest -q")))
        assert analysis.unresolved_variable is False

    def test_relative_write_operand_still_extracts(self):
        """Only variable references go to no-verdict; a plain relative
        operand still surfaces so consumers resolve it against the cwd.
        """
        analysis = analyze_payload_write_targets(_bash("echo hi > notes.md"))
        assert analysis.targets == ["notes.md"]
        assert analysis.unresolved_variable is False

    def test_variable_write_verb_operand_resolves(self):
        payload = _bash(f"_t=$(mktemp {CAPTURE_TEMPLATE})\ntouch \"$_t\"")
        assert extract_payload_write_targets(payload) == [CAPTURE_TEMPLATE]

    def test_session_cwd_extractor_resolves_the_same_token(self):
        command = f"_t=$(mktemp {CAPTURE_TEMPLATE})\ncat /etc/hosts > \"$_t\""
        assert CAPTURE_TEMPLATE in extract_command_targets(command)

    def test_unbound_variable_target_is_dropped_by_both_extractors(self):
        command = 'cat /etc/hosts > "$CAPTURE"'
        assert extract_command_targets(command) == ["/etc/hosts"]
        assert extract_payload_write_targets(_bash(command)) == []


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees").mkdir(parents=True)
    return repo_path


def _seed_lane(conn, repo, *, session_id="sid-capture", item_id=2013):
    register_machine_checkout(
        Path(repo).parent / "machine-config", Path(repo), project_id=1,
    )
    seed_item(
        conn, item_id=item_id, branch=f"YOK-{item_id}", status="implementing",
        repo_path=repo,
    )
    seed_item_claim(conn, session_id, item_id=item_id)
    worktree = repo / ".worktrees" / f"YOK-{item_id}"
    worktree.mkdir(parents=True, exist_ok=True)
    return worktree


class TestCaptureFirstLaneGuard:
    """End-to-end: the harness cwd stays on main while the lane is held."""

    def test_capture_first_command_is_allowed_from_main_cwd(self, conn, repo):
        _seed_lane(conn, repo)
        verdict = lint_lane_main_write.evaluate_pre_tool_use({
            "session_id": "sid-capture",
            "tool_name": "Bash",
            "cwd": str(repo),
            "tool_input": {"command": _capture_first("ruff check runtime")},
        })
        assert verdict.allow is True

    def test_lane_git_commit_with_temp_capture_is_allowed(self, conn, repo):
        worktree = _seed_lane(conn, repo)
        command = _capture_first(f'git -C {worktree} commit -m "msg"')
        verdict = lint_lane_main_write.evaluate_pre_tool_use({
            "session_id": "sid-capture",
            "tool_name": "Bash",
            "cwd": str(repo),
            "tool_input": {"command": command},
        })
        assert verdict.allow is True

    def test_unresolvable_capture_variable_withholds_a_verdict(self, conn, repo):
        _seed_lane(conn, repo)
        verdict = lint_lane_main_write.evaluate_pre_tool_use({
            "session_id": "sid-capture",
            "tool_name": "Bash",
            "cwd": str(repo),
            "tool_input": {"command": 'pytest -q > "$CAPTURE"'},
        })
        assert verdict.allow is True

    def test_relative_main_write_still_denies(self, conn, repo):
        """The cwd fallback survives for operands that name no variable."""
        _seed_lane(conn, repo)
        with mock.patch.object(
            lint_lane_main_write, "emit_denied", return_value=None,
        ):
            verdict = lint_lane_main_write.evaluate_pre_tool_use({
                "session_id": "sid-capture",
                "tool_name": "Bash",
                "cwd": str(repo),
                "tool_input": {"command": "echo hi > runtime/api/foo.py"},
            })
        assert verdict.allow is False

    def test_capture_variable_pointing_into_main_still_denies(self, conn, repo):
        """Resolution is not an exemption: a variable assigned a main path
        classifies exactly as the literal write it stands for.
        """
        _seed_lane(conn, repo)
        target = repo / "runtime/api/foo.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        with mock.patch.object(
            lint_lane_main_write, "emit_denied", return_value=None,
        ):
            verdict = lint_lane_main_write.evaluate_pre_tool_use({
                "session_id": "sid-capture",
                "tool_name": "Bash",
                "cwd": str(repo),
                "tool_input": {"command": f'out={target}\necho hi > "$out"'},
            })
        assert verdict.allow is False
        assert str(target) in verdict.reason
