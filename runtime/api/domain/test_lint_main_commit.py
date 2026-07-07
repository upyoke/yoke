"""Tests for yoke_core.domain.lint_main_commit (typed evaluate)."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from yoke_core.domain import lint_main_commit, lint_staged_union
from runtime.harness.hook_runner.types import HookContext, Next, Outcome


def _payload(command: str) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "sess-test",
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }


def _record_for(payload: dict) -> HookContext:
    return lint_main_commit._build_context_from_payload(payload)


class TestIsBookkeeping(unittest.TestCase):
    def test_exact_matches(self) -> None:
        self.assertTrue(lint_main_commit.is_bookkeeping("AGENTS.md"))
        self.assertTrue(lint_main_commit.is_bookkeeping("CLAUDE.md"))

    def test_prefix_matches(self) -> None:
        self.assertTrue(lint_main_commit.is_bookkeeping("ouroboros/patterns.md"))
        self.assertTrue(lint_main_commit.is_bookkeeping(".claude/agents/x.md"))
        self.assertTrue(lint_main_commit.is_bookkeeping(".agents/skills/yoke/scripts/foo.sh"))

    def test_root_data_paths_are_not_bookkeeping(self) -> None:
        self.assertFalse(lint_main_commit.is_bookkeeping("data/orphan.md"))
        self.assertFalse(lint_main_commit.is_bookkeeping("data/orphan.log"))

    def test_legacy_project_qa_artifacts_are_not_bookkeeping(self) -> None:
        self.assertFalse(
            lint_main_commit.is_bookkeeping("projects/buzz/qa-artifacts/screenshot.png")
        )

    def test_non_bookkeeping(self) -> None:
        self.assertFalse(lint_main_commit.is_bookkeeping("runtime/api/domain/foo.py"))
        self.assertFalse(lint_main_commit.is_bookkeeping("src/main.rs"))
        self.assertFalse(lint_main_commit.is_bookkeeping("README.md"))


class TestExtractCommand(unittest.TestCase):
    def test_tool_input_command(self) -> None:
        self.assertEqual(
            lint_main_commit._extract_command({"tool_input": {"command": "git status"}}),
            "git status",
        )

    def test_camel_case(self) -> None:
        self.assertEqual(
            lint_main_commit._extract_command({"toolInput": {"command": "ls"}}),
            "ls",
        )

    def test_cmd_fallback(self) -> None:
        self.assertEqual(
            lint_main_commit._extract_command({"tool_input": {"cmd": "git log"}}),
            "git log",
        )

    def test_top_level_command(self) -> None:
        self.assertEqual(
            lint_main_commit._extract_command({"command": "echo hi"}),
            "echo hi",
        )

    def test_empty(self) -> None:
        self.assertEqual(lint_main_commit._extract_command({}), "")


class TestEvaluatePayload(unittest.TestCase):
    def test_no_git_commit_allows(self) -> None:
        self.assertIsNone(lint_main_commit.evaluate_payload(_payload("git status")))

    def test_bypass_comment_allows(self) -> None:
        self.assertIsNone(
            lint_main_commit.evaluate_payload(
                _payload("git commit -m 'foo'  # lint:no-main-check")
            )
        )

    def test_non_main_branch_allows(self) -> None:
        with mock.patch.object(lint_main_commit, "_current_branch", return_value="feature-xyz"):
            self.assertIsNone(
                lint_main_commit.evaluate_payload(_payload("git commit -m 'foo'"))
            )

    def test_no_staged_files_allows(self) -> None:
        with mock.patch.object(lint_main_commit, "_current_branch", return_value="main"), \
             mock.patch.object(lint_main_commit, "_staged_files", return_value=[]):
            self.assertIsNone(
                lint_main_commit.evaluate_payload(_payload("git commit -m 'foo'"))
            )

    def test_all_bookkeeping_allows(self) -> None:
        with mock.patch.object(lint_main_commit, "_current_branch", return_value="main"), \
             mock.patch.object(
                lint_main_commit,
                "_staged_files",
                return_value=["AGENTS.md", "ouroboros/patterns.md"],
            ):
            self.assertIsNone(
                lint_main_commit.evaluate_payload(_payload("git commit -m 'foo'"))
            )

    def test_no_active_items_allows(self) -> None:
        with mock.patch.object(lint_main_commit, "_current_branch", return_value="main"), \
             mock.patch.object(
                lint_main_commit,
                "_staged_files",
                return_value=["runtime/api/domain/foo.py"],
            ), \
             mock.patch.object(lint_main_commit, "_active_worktree_items", return_value=[]):
            self.assertIsNone(
                lint_main_commit.evaluate_payload(_payload("git commit -m 'foo'"))
            )

    def test_blocks_with_active_items(self) -> None:
        with mock.patch.object(lint_main_commit, "_current_branch", return_value="main"), \
             mock.patch.object(
                lint_main_commit,
                "_staged_files",
                return_value=["runtime/api/domain/foo.py", "ouroboros/patterns.md"],
            ), \
             mock.patch.object(
                lint_main_commit,
                "_active_worktree_items",
                return_value=["42|Some item", "99|Another"],
            ):
            reason = lint_main_commit.evaluate_payload(_payload("git commit -m 'foo'"))
            self.assertIsNotNone(reason)
            assert reason is not None
            self.assertIn("BLOCKED", reason)
            self.assertIn("runtime/api/domain/foo.py", reason)
            self.assertIn("YOK-42", reason)

    def test_master_branch_also_blocks(self) -> None:
        # `git commit -a` self-stages, so the effective set widens to the
        # modified/untracked probe — pinned here for hermeticity.
        with mock.patch.object(lint_main_commit, "_current_branch", return_value="master"), \
             mock.patch.object(
                lint_main_commit,
                "_staged_files",
                return_value=["src/main.rs"],
            ), \
             mock.patch.object(
                lint_staged_union,
                "_modified_and_untracked",
                return_value=["src/main.rs"],
            ), \
             mock.patch.object(
                lint_main_commit,
                "_active_worktree_items",
                return_value=["1|Something"],
            ):
            reason = lint_main_commit.evaluate_payload(_payload("git commit -am 'x'"))
            self.assertIsNotNone(reason)


class TestEvaluate(unittest.TestCase):
    def test_allow_returns_noop(self) -> None:
        decision = lint_main_commit.evaluate(_record_for(_payload("git status")))
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertIs(decision.next, Next.CONTINUE)
        self.assertEqual(decision.message, "")
        self.assertFalse(decision.block)

    def test_deny_carries_envelope_and_block(self) -> None:
        payload = _payload("git commit -m 'wip'")
        with mock.patch.object(lint_main_commit, "_current_branch", return_value="main"), \
             mock.patch.object(
                lint_main_commit,
                "_staged_files",
                return_value=["runtime/api/domain/foo.py"],
            ), \
             mock.patch.object(
                lint_main_commit,
                "_active_worktree_items",
                return_value=["7|thing"],
            ), \
             mock.patch.object(lint_main_commit, "_emit_denial") as emit_mock:
            decision = lint_main_commit.evaluate(_record_for(payload))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertIs(decision.next, Next.STOP)
        self.assertTrue(decision.block)
        parsed = json.loads(decision.message)
        self.assertEqual(
            parsed["hookSpecificOutput"]["permissionDecision"], "deny"
        )
        self.assertIn(
            "BLOCKED", parsed["hookSpecificOutput"]["permissionDecisionReason"]
        )
        emit_mock.assert_called_once()

    def test_non_dict_payload_returns_noop(self) -> None:
        record = HookContext(
            event_name="PreToolUse",
            executor_family="claude",
            executor_surface="claude",
            payload={},
        )
        decision = lint_main_commit.evaluate(record)
        self.assertIs(decision.outcome, Outcome.NOOP)


class TestMain(unittest.TestCase):
    def test_invalid_json_returns_zero_no_output(self) -> None:
        buf = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("not-json")), redirect_stdout(buf):
            rc = lint_main_commit.main()
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue(), "")

    def test_allow_produces_no_output(self) -> None:
        payload = _payload("git status")
        buf = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), \
             redirect_stdout(buf):
            rc = lint_main_commit.main()
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue(), "")

    def test_deny_prints_envelope(self) -> None:
        payload = _payload("git commit -m 'wip'")
        buf = io.StringIO()
        with mock.patch.object(lint_main_commit, "_current_branch", return_value="main"), \
             mock.patch.object(
                lint_main_commit,
                "_staged_files",
                return_value=["runtime/api/domain/foo.py"],
            ), \
             mock.patch.object(
                lint_main_commit,
                "_active_worktree_items",
                return_value=["7|thing"],
            ), \
             mock.patch.object(lint_main_commit, "_emit_denial"), \
             mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), \
             redirect_stdout(buf):
            rc = lint_main_commit.main()
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue().strip())
        self.assertEqual(
            parsed["hookSpecificOutput"]["permissionDecision"], "deny"
        )


class TestQuotedGitCommitEvidence(unittest.TestCase):
    """AC-5 regression: text containing ``git commit`` inside quoted CLI
    arguments must not trigger the main-commit lint as a real commit."""

    def test_field_note_evidence_text_is_allowed(self) -> None:
        # A field-note append whose --evidence argument quotes the
        # phrase "git commit" must not be classified as an actual
        # commit invocation. The branch/staged/items lookups must not
        # even run -- the classifier short-circuits earlier.
        cmd = (
            "yoke ouroboros field-note append --kind failed "
            "--evidence \"previous attempt: git commit was blocked\""
        )
        payload = _payload(cmd)
        with mock.patch.object(lint_main_commit, "_current_branch") as branch, \
             mock.patch.object(lint_main_commit, "_staged_files") as staged, \
             mock.patch.object(
                lint_main_commit, "_active_worktree_items"
            ) as active:
            result = lint_main_commit.evaluate_payload(payload)
            self.assertIsNone(result)
            branch.assert_not_called()
            staged.assert_not_called()
            active.assert_not_called()


if __name__ == "__main__":
    unittest.main()
