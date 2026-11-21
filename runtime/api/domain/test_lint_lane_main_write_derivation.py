"""A lane-main-write refusal must show how it reached the path it refused."""

from __future__ import annotations

import json
import re
from pathlib import Path
from yoke_contracts.hook_tool_names import canonicalize_shell_payload
from yoke_contracts.hook_runner.repo_paths import normalize_repo_path
from unittest import mock

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_lane_main_write
from yoke_core.domain.lint_lane_main_write_derivation import (
    COMMAND_TOKEN,
    GIT_STATE_CHANGE,
    RECOVERY_MESSAGE_FILE,
    TOOL_TARGET,
    UNREADABLE_DESTINATION,
    TargetDerivation,
    format_derivation_guidance,
)
from yoke_core.domain.lint_session_cwd_path_authority import is_free_path
from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree
from yoke_harness.hooks.shell_kind_stamp import stamp_shell_kind
from yoke_core.domain.lint_lane_main_write_messages import format_denial
from yoke_core.domain.lint_python_write_target_extract import (
    analyze_python_heredoc_writes,
)

SESSION = "sid-derivation"
ITEM_ID = 2451


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees").mkdir(parents=True)
    return repo_path


def _seed_lane(conn, repo) -> Path:
    register_machine_checkout(
        Path(repo).parent / "machine-config",
        Path(repo),
        project_id=1,
    )
    seed_item(
        conn,
        item_id=ITEM_ID,
        branch=f"YOK-{ITEM_ID}",
        status="implementing",
        repo_path=repo,
    )
    seed_item_claim(conn, SESSION, item_id=ITEM_ID)
    lane = repo / ".worktrees" / f"YOK-{ITEM_ID}"
    lane.mkdir(parents=True, exist_ok=True)
    return lane


def _evaluate(command: str, repo: Path):
    with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
        return lint_lane_main_write.evaluate_pre_tool_use(
            {
                "session_id": SESSION,
                "tool_name": "Bash",
                "cwd": str(repo),
                "tool_input": {"command": command},
            }
        )


def _mention_only_heredoc(lane_file: Path, mentioned: str) -> str:
    """A body that edits an in-lane file and only quotes *mentioned* as text."""
    return (
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        f"stale_reference = {mentioned!r}\n"
        f"doc = Path({str(lane_file)!r})\n"
        "doc.write_text(doc.read_text().replace(stale_reference, ''))\n"
        "PY"
    )


def _computed_target_heredoc(lane: Path) -> str:
    """A body whose write destinations are joined at runtime."""
    return (
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        f"root = Path({str(lane)!r})\n"
        "for rel in ['docs/a.md', 'docs/b.md']:\n"
        "    (root / rel).write_text('changed')\n"
        "PY"
    )


class TestMentionIsNotAWriteTarget:
    def test_mentioned_relative_path_is_not_extracted(self, tmp_path):
        command = _mention_only_heredoc(
            tmp_path / "lane" / "AGENTS.md",
            "docs/reference/legacy.md",
        )
        analysis = analyze_python_heredoc_writes(command)
        assert analysis.detected is True
        assert "docs/reference/legacy.md" not in analysis.targets
        assert analysis.unresolved_writes == ()

    def test_heredoc_mentioning_repo_relative_path_is_allowed(self, conn, repo):
        lane = _seed_lane(conn, repo)
        command = _mention_only_heredoc(
            lane / "AGENTS.md",
            "docs/reference/legacy.md",
        )
        verdict = _evaluate(command, repo)
        assert verdict.allow is True
        assert verdict.attempted_path == ""


class TestExtractedTargetRefusal:
    def test_relative_token_refusal_names_token_and_resolution(self, conn, repo):
        _seed_lane(conn, repo)
        verdict = _evaluate("touch docs/notes.md", repo)
        assert verdict.allow is False
        assert verdict.derivation is not None
        assert verdict.derivation.source == COMMAND_TOKEN
        assert verdict.derivation.token == "docs/notes.md"
        assert "Extracted:     docs/notes.md" in verdict.reason
        assert f"working directory {repo} -> {repo / 'docs/notes.md'}" in verdict.reason
        assert f"Main checkout: {normalize_repo_path(str(repo))}" in verdict.reason

    def test_tool_target_refusal_names_the_file_path(self, conn, repo):
        _seed_lane(conn, repo)
        target = repo / "runtime/api/foo.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
            verdict = lint_lane_main_write.evaluate_pre_tool_use(
                {
                    "session_id": SESSION,
                    "tool_name": "Write",
                    "tool_input": {"file_path": str(target)},
                }
            )
        assert verdict.allow is False
        assert verdict.derivation.source == TOOL_TARGET
        assert f"Extracted:     {target}" in verdict.reason
        assert "already an absolute path" in verdict.reason


class TestWorkingDirectoryFallbackRefusal:
    def test_computed_destination_refusal_names_the_fallback(self, conn, repo):
        lane = _seed_lane(conn, repo)
        verdict = _evaluate(_computed_target_heredoc(lane), repo)
        assert verdict.allow is False
        assert verdict.derivation.source == UNREADABLE_DESTINATION
        assert verdict.derivation.token == ""
        assert "no readable write destination" in verdict.reason
        assert f"fell back to the working directory {repo}" in verdict.reason
        assert "Unresolved:    (root / rel).write_text(...)" in verdict.reason

    def test_fallback_guidance_differs_from_extracted_target(self, conn, repo):
        lane = _seed_lane(conn, repo)
        fallback = _evaluate(_computed_target_heredoc(lane), repo)
        extracted = _evaluate("touch docs/notes.md", repo)
        assert fallback.allow is False and extracted.allow is False
        assert "literal absolute lane path" in fallback.reason
        assert "literal absolute lane path" not in extracted.reason
        assert "Copy the in-lane path above" in extracted.reason
        assert "Copy the in-lane path above" not in fallback.reason


class TestProjectAgnosticMessages:
    """No refusal line may name a path the caller did not supply."""

    def test_rendered_denial_only_names_supplied_paths(self):
        supplied = [
            "/checkout/docs/guide.md",
            "/checkout/.lanes/one",
            "/checkout/.lanes/one/docs/guide.md",
            "/checkout",
        ]
        reason = format_denial(
            item_label="ONE",
            lane_path=supplied[1],
            attempted_path=supplied[0],
            lane_equivalent=supplied[2],
            suppression_seen=False,
            derivation=TargetDerivation(
                source=COMMAND_TOKEN,
                token="docs/guide.md",
                working_directory=supplied[3],
                main_checkout=supplied[3],
            ),
        )
        absolute_paths = re.findall(r"(?<![\w.])/[\w./-]+", reason)
        assert absolute_paths
        for found in absolute_paths:
            assert any(found == path for path in supplied), found
        assert ".worktrees" not in reason

    def test_fallback_denial_only_names_supplied_paths_and_the_recipe(self):
        """The cwd-fallback branch adds exactly one literal: the temp file."""
        supplied = [
            "/checkout/docs/guide.md",
            "/checkout/.lanes/one",
            "/checkout/.lanes/one/docs/guide.md",
            "/checkout",
        ]
        reason = format_denial(
            item_label="ONE",
            lane_path=supplied[1],
            attempted_path=supplied[3],
            lane_equivalent=supplied[1],
            suppression_seen=False,
            derivation=TargetDerivation(
                source=UNREADABLE_DESTINATION,
                working_directory=supplied[3],
                main_checkout=supplied[3],
            ),
        )
        allowed = [*supplied, RECOVERY_MESSAGE_FILE]
        for found in re.findall(r"(?<![\w.])/[\w./-]+", reason):
            assert any(found == path for path in allowed), found
        assert f"git -C {supplied[1]} commit" in reason


class TestComputedCommitMessageRecovery:
    """The refusal must name a recovery the refused caller can run.

    A computed commit message leaves the Git command's effective working
    directory intact, including a leading absolute ``cd``.
    """

    def _computed_commit(self, lane: Path) -> str:
        return (
            f"cd {Path(lane).as_posix()} && git commit -m \"$(cat <<'EOF'\n"
            "Fix the thing\n"
            "\n"
            "Longer body explaining why.\n"
            "EOF\n"
            ')"'
        )

    def test_computed_commit_message_uses_leading_lane_cd(
        self,
        conn,
        repo,
    ):
        lane = _seed_lane(conn, repo)
        verdict = _evaluate(self._computed_commit(lane), repo)
        assert verdict.allow is True

    def test_computed_commit_on_main_still_denies(self, conn, repo):
        _seed_lane(conn, repo)
        verdict = _evaluate(self._computed_commit(repo), repo)
        assert verdict.allow is False
        assert verdict.derivation.source == GIT_STATE_CHANGE
        assert f"Git runs in {repo}" in verdict.reason
        assert "unreadable destination" not in verdict.reason

    def test_computed_commit_refusal_names_the_lane_recovery(self, conn, repo):
        lane = _seed_lane(conn, repo)
        verdict = _evaluate(self._computed_commit(repo), repo)
        assert f"git -C {Path(lane).as_posix()} commit -F {RECOVERY_MESSAGE_FILE}" in verdict.reason

    def test_refusal_teaches_the_effective_workdir(
        self,
        conn,
        repo,
    ):
        lane = _seed_lane(conn, repo)
        verdict = _evaluate(self._computed_commit(repo), repo)
        assert f"declare {Path(lane).as_posix()} as the call's workdir" in verdict.reason
        assert f"make `cd {Path(lane).as_posix()}` the command's first statement" in verdict.reason

    def test_recovery_message_file_is_readable_from_a_claimed_lane(self):
        assert is_free_path(RECOVERY_MESSAGE_FILE)

    def test_guidance_without_a_lane_path_stays_a_placeholder(self):
        guidance = format_derivation_guidance(
            TargetDerivation(source=UNREADABLE_DESTINATION, working_directory="/w"),
        )
        assert "git -C <lane path> commit" in guidance


@pytest.mark.parametrize("command", [
    "git commit -m x", "git add a.py", "git mv a.py b.py",
    "git stash", "git checkout other",
])
@pytest.mark.parametrize(("cwd", "shell_kind"), [
    ("/repo", "bash"),
    (r"C:\Repo", "powershell"),
    ("C:/Repo", "powershell"),
    (r"C:\Repo", None),
])
def test_git_state_change_names_command_and_held_lane(command, cwd, shell_kind):
    lane = f"{cwd}/.worktrees/YOK-{ITEM_ID}"
    payload = {
        "session_id": SESSION,
        "tool_name": "Bash",
        "cwd": cwd,
        "tool_input": {"command": command, "workdir": cwd},
    }
    if shell_kind is None:
        payload = json.loads(stamp_shell_kind(json.dumps(payload), "codex", windows=True))
        assert payload["yoke_shell_kind"] == "powershell"
    else:
        payload["yoke_shell_kind"] = shell_kind
    with (
        mock.patch.object(lint_lane_main_write, "_open_conn"),
        mock.patch.object(lint_lane_main_write, "claimed_worktrees",
                          return_value=[ClaimedWorktree(ITEM_ID, None, lane)]),
        mock.patch.object(lint_lane_main_write, "_lane_is_active", return_value=True),
        mock.patch.object(lint_lane_main_write, "derive_repo_roots", return_value=[cwd]),
        mock.patch.object(lint_lane_main_write, "item_label", return_value=f"YOK-{ITEM_ID}"),
        mock.patch.object(lint_lane_main_write, "emit_denied"),
    ):
        verdict = lint_lane_main_write.evaluate_pre_tool_use(canonicalize_shell_payload(payload))
    subcommand = command.split()[1]
    assert not verdict.allow
    assert f"git {subcommand} changes the main checkout" in verdict.reason
    assert f"YOK-{ITEM_ID}'s lane is open at {lane}" in verdict.reason
    assert "unreadable destination" not in verdict.reason


def test_unbound_redirect_keeps_unreadable_destination_reason(conn, repo):
    _seed_lane(conn, repo)
    verdict = _evaluate('echo x > "$F"', repo)
    assert not verdict.allow
    assert "unreadable destination" in verdict.reason
