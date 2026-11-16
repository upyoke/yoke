"""Tests for hint_file_line_limit_approach.

Covers the rule-1/2/3 hint emission (matching the structural commit
gate's three rules), the allowed shapes (under-cap, non-authored
classification, missing file_path), and the typed entry returning
NOOP + additionalContext.
"""

from __future__ import annotations

import unittest

from yoke_core.domain import hint_file_line_limit_approach as hint
from yoke_core.domain.file_line_check import Classification
from yoke_core.hooks.types import Outcome

# A non-default limit proves the hint uses the limit it is given.
LIMIT = 200


def _content(n: int) -> str:
    return "x\n" * n


def _payload(file_path: str, content: str) -> dict:
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
        "session_id": "sess-test",
    }


class TestEvaluateFields(unittest.TestCase):
    """Pure-helper rule coverage."""

    def test_new_file_over_cap_hints(self) -> None:
        # Rule 1: new file lands over cap.
        result = hint.evaluate_fields(
            "runtime/api/domain/new_thing.py",
            _content(LIMIT + 5),
            existing_line_count=0,
            classification=Classification.AUTHORED,
            limit=LIMIT,
        )
        self.assertIsNotNone(result)
        self.assertIn(str(LIMIT), result)

    def test_existing_under_cap_grows_past_hints(self) -> None:
        # Rule 3: existing under-cap file crosses upward.
        result = hint.evaluate_fields(
            "runtime/api/domain/x.py",
            _content(LIMIT + 1),
            existing_line_count=LIMIT - 10,
            classification=Classification.AUTHORED,
            limit=LIMIT,
        )
        self.assertIsNotNone(result)

    def test_existing_over_cap_grows_further_hints(self) -> None:
        # Rule 2: over-cap file growing further.
        result = hint.evaluate_fields(
            "runtime/api/domain/x.py",
            _content(LIMIT + 20),
            existing_line_count=LIMIT + 5,
            classification=Classification.AUTHORED,
            limit=LIMIT,
        )
        self.assertIsNotNone(result)

    def test_under_cap_no_hint(self) -> None:
        # File well under cap — no hint.
        result = hint.evaluate_fields(
            "runtime/api/domain/x.py",
            _content(100),
            existing_line_count=50,
            classification=Classification.AUTHORED,
            limit=LIMIT,
        )
        self.assertIsNone(result)

    def test_at_cap_exactly_no_hint(self) -> None:
        # Exactly at cap is allowed (the gate uses `new <= limit`).
        result = hint.evaluate_fields(
            "runtime/api/domain/x.py",
            _content(LIMIT),
            existing_line_count=LIMIT - 5,
            classification=Classification.AUTHORED,
            limit=LIMIT,
        )
        self.assertIsNone(result)

    def test_over_cap_shrinking_no_hint(self) -> None:
        # Existing over-cap file shrinking (even if still over) — no hint.
        # This is good direction; the agent is fixing the problem.
        result = hint.evaluate_fields(
            "runtime/api/domain/x.py",
            _content(LIMIT + 3),
            existing_line_count=LIMIT + 20,
            classification=Classification.AUTHORED,
            limit=LIMIT,
        )
        self.assertIsNone(result)

    def test_non_authored_classification_no_hint(self) -> None:
        # Generated files, lockfiles, etc. — out of scope for the cap.
        result = hint.evaluate_fields(
            ".yoke/BOARD.md",
            _content(1000),
            existing_line_count=500,
            classification=Classification.GENERATED,
            limit=LIMIT,
        )
        self.assertIsNone(result)

    def test_missing_file_path_no_hint(self) -> None:
        result = hint.evaluate_fields(
            "", _content(1000), 0, Classification.AUTHORED, LIMIT,
        )
        self.assertIsNone(result)


class TestTypedEntry(unittest.TestCase):
    """The typed entry returns NOOP + additionalContext when appropriate."""

    def test_non_write_tool_noop(self) -> None:
        payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        decision = hint.evaluate(hint._build_context_from_payload(payload))
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertNotIn("additionalContext", decision.audit_fields or {})

    def test_write_hint_uses_project_file_line_limit(self) -> None:
        import os
        import pathlib
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".yoke").mkdir()
            (root / ".yoke/project.config").write_text("file_line_limit=200\n")
            payload = _payload(str(root / "src/new.py"), _content(201))
            with mock.patch.dict(os.environ, {"YOKE_TARGET_REPO_ROOT": tmp}):
                decision = hint.evaluate(hint._build_context_from_payload(payload))
        context = (decision.audit_fields or {}).get("additionalContext", "")
        self.assertIn("over the 200-line authored-file cap", context)

    def test_missing_payload_fields_noop(self) -> None:
        payload = {"tool_name": "Write"}  # no tool_input
        decision = hint.evaluate(hint._build_context_from_payload(payload))
        self.assertIs(decision.outcome, Outcome.NOOP)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
