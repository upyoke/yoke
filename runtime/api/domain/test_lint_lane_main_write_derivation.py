"""A lane-main-write refusal must show how it reached the path it refused."""

from __future__ import annotations

import re
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
from yoke_core.domain.lint_lane_main_write_derivation import (
    COMMAND_TOKEN,
    RECOVERY_MESSAGE_FILE,
    TOOL_TARGET,
    WORKING_DIRECTORY,
    TargetDerivation,
    format_derivation_guidance,
)
from yoke_core.domain.lint_session_cwd_path_authority import is_free_path
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
        Path(repo).parent / "machine-config", Path(repo), project_id=1,
    )
    seed_item(
        conn, item_id=ITEM_ID, branch=f"YOK-{ITEM_ID}", status="implementing",
        repo_path=repo,
    )
    seed_item_claim(conn, SESSION, item_id=ITEM_ID)
    lane = repo / ".worktrees" / f"YOK-{ITEM_ID}"
    lane.mkdir(parents=True, exist_ok=True)
    return lane


def _evaluate(command: str, repo: Path):
    with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
        return lint_lane_main_write.evaluate_pre_tool_use({
            "session_id": SESSION,
            "tool_name": "Bash",
            "cwd": str(repo),
            "tool_input": {"command": command},
        })


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
            tmp_path / "lane" / "AGENTS.md", "docs/reference/legacy.md",
        )
        analysis = analyze_python_heredoc_writes(command)
        assert analysis.detected is True
        assert "docs/reference/legacy.md" not in analysis.targets
        assert analysis.unresolved_writes == ()

    def test_heredoc_mentioning_repo_relative_path_is_allowed(self, conn, repo):
        lane = _seed_lane(conn, repo)
        command = _mention_only_heredoc(
            lane / "AGENTS.md", "docs/reference/legacy.md",
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
        assert f"working directory {repo} -> {repo}/docs/notes.md" in verdict.reason
        assert f"Main checkout: {repo}" in verdict.reason

    def test_tool_target_refusal_names_the_file_path(self, conn, repo):
        _seed_lane(conn, repo)
        target = repo / "runtime/api/foo.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
            verdict = lint_lane_main_write.evaluate_pre_tool_use({
                "session_id": SESSION,
                "tool_name": "Write",
                "tool_input": {"file_path": str(target)},
            })
        assert verdict.allow is False
        assert verdict.derivation.source == TOOL_TARGET
        assert f"Extracted:     {target}" in verdict.reason
        assert "already an absolute path" in verdict.reason


class TestWorkingDirectoryFallbackRefusal:
    def test_computed_destination_refusal_names_the_fallback(self, conn, repo):
        lane = _seed_lane(conn, repo)
        verdict = _evaluate(_computed_target_heredoc(lane), repo)
        assert verdict.allow is False
        assert verdict.derivation.source == WORKING_DIRECTORY
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
            mode="deny",
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
            mode="deny",
            suppression_seen=False,
            derivation=TargetDerivation(
                source=WORKING_DIRECTORY,
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

    A commit whose message is built by a command substitution has no
    readable write target, so the guard falls back to the call's declared
    working directory. Telling that caller to "run it from the lane" is
    the advice they already followed with a leading ``cd``, which the
    guard never reads — so the refusal names the lane on the command.
    """

    def _computed_commit(self, lane: Path) -> str:
        return (
            f"cd {lane} && git commit -m \"$(cat <<'EOF'\n"
            "Fix the thing\n"
            "\n"
            "Longer body explaining why.\n"
            "EOF\n"
            ")\""
        )

    def test_computed_commit_message_falls_back_to_the_declared_cwd(
        self, conn, repo,
    ):
        lane = _seed_lane(conn, repo)
        verdict = _evaluate(self._computed_commit(lane), repo)
        assert verdict.allow is False
        assert verdict.derivation.source == WORKING_DIRECTORY
        assert f"fell back to the working directory {repo}" in verdict.reason

    def test_computed_commit_refusal_names_the_lane_recovery(self, conn, repo):
        lane = _seed_lane(conn, repo)
        verdict = _evaluate(self._computed_commit(lane), repo)
        assert (
            f"git -C {lane} commit -F {RECOVERY_MESSAGE_FILE}"
            in verdict.reason
        )

    def test_refusal_says_a_leading_cd_does_not_move_the_fallback(
        self, conn, repo,
    ):
        lane = _seed_lane(conn, repo)
        verdict = _evaluate(self._computed_commit(lane), repo)
        assert "leading `cd` in the command body does not move" in verdict.reason

    def test_recovery_message_file_is_readable_from_a_claimed_lane(self):
        assert is_free_path(RECOVERY_MESSAGE_FILE)

    def test_guidance_without_a_lane_path_stays_a_placeholder(self):
        guidance = format_derivation_guidance(
            TargetDerivation(source=WORKING_DIRECTORY, working_directory="/w"),
        )
        assert "git -C <lane path> commit" in guidance
