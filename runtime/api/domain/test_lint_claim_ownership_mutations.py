"""Tests for yoke_core.domain.lint_claim_ownership_mutations."""

from __future__ import annotations

import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from yoke_core.domain import db_backend
from yoke_core.domain import lint_claim_ownership_mutations as lint
from yoke_core.domain.db_helpers import iso8601_now
from runtime.api.fixtures.file_test_db import init_test_db
from runtime.harness.hook_runner.types import HookContext, Next, Outcome


_AMBIENT = "sess-self"
_FOREIGN = "sess-other"


def _payload(command: str, session_id: str = _AMBIENT) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": session_id,
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }


def _record(payload: dict) -> HookContext:
    sid = payload.get("session_id")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude", executor_surface="claude",
        payload=payload, tool_name="Bash",
        command_body=lint._extract_command(payload) or None,
        cwd=None, session_id=sid if isinstance(sid, str) else None,
    )


class TestClassifyMutation(unittest.TestCase):
    def test_mutating_command_families(self) -> None:
        cases = [
            (
                "python3 -m yoke_core.api.service_client claim-work --item YOK-1",
                "service-client/claim-work",
            ),
            (
                "python3 -m yoke_core.api.service_client release-work-claim --item YOK-1",
                "service-client/release-work-claim",
            ),
            (
                "python3 -m yoke_core.api.service_client path-claim-widen --claim-id 9",
                "service-client/path-claim-widen",
            ),
            (
                "python3 -m yoke_core.api.service_client backlog-cli sync-item 1",
                "backlog-cli/sync-item",
            ),
            (
                "python3 -m yoke_core.api.service_client backlog-cli post-comment 1 a b",
                "backlog-cli/post-comment",
            ),
            (
                "python3 -m yoke_core.cli.db_router items update 1 status x",
                "db-router/items/update",
            ),
            (
                "python3 -m yoke_core.cli.db_router sections upsert 1 X",
                "db-router/sections/upsert",
            ),
            (
                "python3 -m yoke_core.domain.item_field_transform append-addendum",
                "domain/item_field_transform",
            ),
        ]
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(lint._classify_mutation(command), expected)

    def test_non_mutating_returns_none(self) -> None:
        for command in [
            "git status",
            "python3 -m runtime.api.unrelated.module foo",
            "python3 -m yoke_core.api.service_client backlog-cli list",
            "python3 -m yoke_core.cli.db_router items get 1 body",
        ]:
            with self.subTest(command=command):
                self.assertIsNone(lint._classify_mutation(command))


class TestIsReadOnlyCommand(unittest.TestCase):
    def test_read_only_substrings_and_db_router_paths(self) -> None:
        for command in [
            "python3 -m runtime.harness.harness_sessions who-claims 1",
            "python3 -m yoke_core.api.service_client path-claim-list",
            "python3 -m yoke_core.api.service_client ownership-guard --item 1",
            "python3 -m yoke_core.api.service_client actors-list",
            "python3 -m yoke_core.cli.db_router items get 1 body",
            "python3 -m yoke_core.cli.db_router query \"SELECT 1\"",
            "python3 -m yoke_core.cli.db_router events list --item 1",
        ]:
            with self.subTest(command=command):
                self.assertTrue(lint._is_read_only_command(command))

    def test_mutating_command_is_not_read_only(self) -> None:
        for command in [
            "python3 -m yoke_core.api.service_client release-work-claim --item 1",
            "python3 -m yoke_core.api.service_client release-work-claim --item 1 --reason who-claims",
            "python3 -m yoke_core.cli.db_router items update 1 status x",
        ]:
            with self.subTest(command=command):
                self.assertFalse(lint._is_read_only_command(command))


class TestExtractors(unittest.TestCase):
    def test_session_id_flag(self) -> None:
        self.assertEqual(
            lint._extract_session_id_flag("cmd --session-id sess-abc more"),
            "sess-abc",
        )
        self.assertEqual(
            lint._extract_session_id_flag("cmd --session-id=sess-abc"),
            "sess-abc",
        )
        self.assertIsNone(lint._extract_session_id_flag("cmd --item YOK-1"))

    def test_item_id(self) -> None:
        self.assertEqual(lint._extract_item_id("cmd --item YOK-42 foo"), 42)
        self.assertEqual(lint._extract_item_id("cmd --item-id 99 foo"), 99)
        self.assertEqual(lint._extract_item_id("cmd --item 7"), 7)
        self.assertEqual(lint._extract_item_id("widen for YOK-100 release"), 100)
        self.assertIsNone(lint._extract_item_id("git status"))


class TestStaticSpoofingBranch(unittest.TestCase):
    def test_foreign_session_id_denies_each_family(self) -> None:
        cases = [
            (
                "python3 -m yoke_core.api.service_client release-work-claim "
                f"--item YOK-1 --session-id {_FOREIGN}",
                "service-client/release-work-claim",
            ),
            (
                "python3 -m yoke_core.api.service_client path-claim-widen "
                f"--claim-id 1 --session-id {_FOREIGN} --paths foo",
                "service-client/path-claim-widen",
            ),
            (
                "python3 -m yoke_core.api.service_client backlog-cli sync-item 1 "
                f"--session-id {_FOREIGN}",
                "backlog-cli/sync-item",
            ),
            (
                "python3 -m yoke_core.cli.db_router items update 1 status x "
                f"--session-id {_FOREIGN}",
                "db-router/items/update",
            ),
        ]
        for command, family in cases:
            with self.subTest(command=command):
                verdict = lint.evaluate_payload(_payload(command))
                self.assertIsNotNone(verdict)
                reason, observed_family = verdict
                self.assertIn("claim-boundary bypass attempt", reason)
                self.assertEqual(observed_family, family)

    def test_same_session_id_allows(self) -> None:
        cmd = (
            "python3 -m yoke_core.api.service_client release-work-claim "
            f"--item YOK-1 --session-id {_AMBIENT}"
        )
        self.assertIsNone(lint.evaluate_payload(_payload(cmd)))

    def test_read_only_with_session_id_allows(self) -> None:
        cmd = (
            "python3 -m yoke_core.api.service_client path-claim-list "
            f"--session-id {_FOREIGN}"
        )
        self.assertIsNone(lint.evaluate_payload(_payload(cmd)))

    def test_suppression_token_does_not_unblock(self) -> None:
        cmd = (
            "python3 -m yoke_core.api.service_client release-work-claim "
            f"--item YOK-1 --session-id {_FOREIGN}  # lint:no-claim-ownership-check"
        )
        verdict = lint.evaluate_payload(_payload(cmd))
        self.assertIsNotNone(verdict)
        assert verdict is not None
        self.assertIn("claim-boundary bypass attempt", verdict[0])


class TestEvaluateContract(unittest.TestCase):
    def test_typed_evaluate_returns_deny_envelope(self) -> None:
        cmd = (
            "python3 -m yoke_core.api.service_client release-work-claim "
            f"--item YOK-1 --session-id {_FOREIGN}"
        )
        with mock.patch.object(lint, "_emit_denial"):
            decision = lint.evaluate(_record(_payload(cmd)))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        self.assertIs(decision.next, Next.STOP)
        envelope = json.loads(decision.message)
        self.assertEqual(
            envelope["hookSpecificOutput"]["permissionDecision"], "deny",
        )
        self.assertEqual(
            decision.audit_fields.get("family"),
            "service-client/release-work-claim",
        )

    def test_typed_evaluate_noop_on_allowed(self) -> None:
        decision = lint.evaluate(_record(_payload("git status")))
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertIs(decision.next, Next.CONTINUE)


if __name__ == "__main__":
    unittest.main()
