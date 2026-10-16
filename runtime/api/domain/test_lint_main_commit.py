"""Tests for yoke_core.domain.lint_main_commit (typed evaluate)."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from yoke_contracts.hook_runner.main_commit import (
    CLIENT_GIT_COMMIT_FACTS_KEY,
    CLIENT_GIT_COMMIT_FACTS_SCHEMA,
)
from yoke_core.domain import lint_main_commit
from yoke_core.hooks.types import HookContext, Next, Outcome

TEST_ITEM_REF = "YOK-42"


def git_facts(branch: str | None, staged: list[str]) -> dict:
    """The client's report of its checkout branch and effective staged set."""
    return {
        CLIENT_GIT_COMMIT_FACTS_KEY: {
            "schema": CLIENT_GIT_COMMIT_FACTS_SCHEMA,
            "is_git_commit": True,
            "repo_cwd": "/client/checkout",
            "branch": branch,
            "staged_paths": staged,
            "staged_probe_ok": True,
            "status_probe_ok": True,
        }
    }


def _payload(command: str, facts: dict | None = None) -> dict:
    return {
        **(facts or {}),
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
        self.assertTrue(
            lint_main_commit.is_bookkeeping(".agents/skills/yoke/scripts/foo.sh")
        )

    def test_root_data_paths_are_not_bookkeeping(self) -> None:
        self.assertFalse(lint_main_commit.is_bookkeeping("data/orphan.md"))
        self.assertFalse(lint_main_commit.is_bookkeeping("data/orphan.log"))

    def test_legacy_project_qa_artifacts_are_not_bookkeeping(self) -> None:
        self.assertFalse(
            lint_main_commit.is_bookkeeping(
                "projects/externalwebapp/qa-artifacts/screenshot.png"
            )
        )

    def test_non_bookkeeping(self) -> None:
        self.assertFalse(lint_main_commit.is_bookkeeping("runtime/api/domain/foo.py"))
        self.assertFalse(lint_main_commit.is_bookkeeping("src/main.rs"))
        self.assertFalse(lint_main_commit.is_bookkeeping("README.md"))


class TestExtractCommand(unittest.TestCase):
    def test_tool_input_command(self) -> None:
        self.assertEqual(
            lint_main_commit._extract_command(
                {"tool_input": {"command": "git status"}}
            ),
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
                _payload(
                    "git commit -m 'foo'  # lint:no-main-check",
                    git_facts("main", ["runtime/api/domain/foo.py"]),
                )
            )
        )

    def test_missing_client_facts_allows(self) -> None:
        with mock.patch.object(
            lint_main_commit, "_active_worktree_items", return_value=["YOK-1|x"]
        ) as active:
            self.assertIsNone(
                lint_main_commit.evaluate_payload(_payload("git commit -m 'foo'"))
            )
        active.assert_not_called()

    def test_non_main_branch_allows(self) -> None:
        facts = git_facts("feature-xyz", ["runtime/api/domain/foo.py"])
        self.assertIsNone(
            lint_main_commit.evaluate_payload(_payload("git commit -m 'foo'", facts))
        )

    def test_unknown_branch_allows(self) -> None:
        facts = git_facts(None, ["runtime/api/domain/foo.py"])
        self.assertIsNone(
            lint_main_commit.evaluate_payload(_payload("git commit -m 'foo'", facts))
        )

    def test_no_staged_files_allows(self) -> None:
        self.assertIsNone(
            lint_main_commit.evaluate_payload(
                _payload("git commit -m 'foo'", git_facts("main", []))
            )
        )

    def test_all_bookkeeping_allows(self) -> None:
        facts = git_facts("main", ["AGENTS.md", "ouroboros/patterns.md"])
        self.assertIsNone(
            lint_main_commit.evaluate_payload(_payload("git commit -m 'foo'", facts))
        )

    def test_no_active_items_allows(self) -> None:
        facts = git_facts("main", ["runtime/api/domain/foo.py"])
        with mock.patch.object(
            lint_main_commit, "_active_worktree_items", return_value=[]
        ):
            self.assertIsNone(
                lint_main_commit.evaluate_payload(
                    _payload("git commit -m 'foo'", facts)
                )
            )

    def test_blocks_with_active_items(self) -> None:
        facts = git_facts(
            "main", ["runtime/api/domain/foo.py", "ouroboros/patterns.md"]
        )
        with mock.patch.object(
            lint_main_commit,
            "_active_worktree_items",
            return_value=[f"{TEST_ITEM_REF}|Some item", "YOK-99|Another"],
        ):
            reason = lint_main_commit.evaluate_payload(
                _payload("git commit -m 'foo'", facts)
            )
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("BLOCKED", reason)
        self.assertIn("runtime/api/domain/foo.py", reason)
        self.assertIn(TEST_ITEM_REF, reason)

    def test_master_branch_also_blocks(self) -> None:
        facts = git_facts("master", ["src/main.rs"])
        with mock.patch.object(
            lint_main_commit, "_active_worktree_items", return_value=["YOK-1|Something"]
        ):
            reason = lint_main_commit.evaluate_payload(
                _payload("git commit -am 'x'", facts)
            )
        self.assertIsNotNone(reason)


class TestEvaluate(unittest.TestCase):
    def test_allow_returns_noop(self) -> None:
        decision = lint_main_commit.evaluate(_record_for(_payload("git status")))
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertIs(decision.next, Next.CONTINUE)
        self.assertEqual(decision.message, "")
        self.assertFalse(decision.block)

    def test_verdict_is_the_same_locally_and_remotely(self) -> None:
        for facts, outcome in (
            (git_facts("main", ["runtime/api/domain/foo.py"]), Outcome.DENY),
            (git_facts("feature", ["runtime/api/domain/foo.py"]), Outcome.NOOP),
            ({}, Outcome.NOOP),
        ):
            payload = _payload("git commit -m 'wip'", facts)
            with (
                mock.patch.object(
                    lint_main_commit, "_active_worktree_items", return_value=["YOK-7|x"]
                ),
                mock.patch.object(lint_main_commit, "_emit_denial"),
            ):
                decisions = [
                    lint_main_commit.evaluate(
                        HookContext(
                            event_name="PreToolUse",
                            executor_family="claude",
                            executor_surface="claude",
                            payload=dict(payload),
                            remote=remote,
                        )
                    )
                    for remote in (False, True)
                ]
            self.assertEqual([d.outcome for d in decisions], [outcome, outcome])
            self.assertEqual(decisions[0].message, decisions[1].message)

    def test_deny_carries_envelope_and_block(self) -> None:
        payload = _payload(
            "git commit -m 'wip'", git_facts("main", ["runtime/api/domain/foo.py"])
        )
        with (
            mock.patch.object(
                lint_main_commit,
                "_active_worktree_items",
                return_value=["YOK-7|thing"],
            ),
            mock.patch.object(lint_main_commit, "_emit_denial") as emit_mock,
        ):
            decision = lint_main_commit.evaluate(_record_for(payload))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertIs(decision.next, Next.STOP)
        self.assertTrue(decision.block)
        parsed = json.loads(decision.message)
        self.assertEqual(parsed["hookSpecificOutput"]["permissionDecision"], "deny")
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
        with (
            mock.patch("sys.stdin", io.StringIO(json.dumps(payload))),
            redirect_stdout(buf),
        ):
            rc = lint_main_commit.main()
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue(), "")

    def test_deny_prints_envelope(self) -> None:
        payload = _payload(
            "git commit -m 'wip'", git_facts("main", ["runtime/api/domain/foo.py"])
        )
        buf = io.StringIO()
        with (
            mock.patch.object(
                lint_main_commit,
                "_active_worktree_items",
                return_value=["YOK-7|thing"],
            ),
            mock.patch.object(lint_main_commit, "_emit_denial"),
            mock.patch("sys.stdin", io.StringIO(json.dumps(payload))),
            redirect_stdout(buf),
        ):
            rc = lint_main_commit.main()
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue().strip())
        self.assertEqual(parsed["hookSpecificOutput"]["permissionDecision"], "deny")


class TestQuotedGitCommitEvidence(unittest.TestCase):
    """Regression: text containing ``git commit`` inside quoted CLI
    arguments must not trigger the main-commit lint as a real commit."""

    def test_field_note_evidence_text_is_allowed(self) -> None:
        # A field-note append whose --evidence argument quotes the
        # phrase "git commit" must not be classified as an actual
        # commit invocation. The items lookup must not even run -- the
        # classifier short-circuits earlier.
        cmd = (
            "yoke ouroboros field-note append --kind failed "
            '--evidence "previous attempt: git commit was blocked"'
        )
        payload = _payload(cmd, git_facts("main", ["runtime/api/domain/foo.py"]))
        with mock.patch.object(lint_main_commit, "_active_worktree_items") as active:
            result = lint_main_commit.evaluate_payload(payload)
            self.assertIsNone(result)
            active.assert_not_called()


if __name__ == "__main__":
    unittest.main()
