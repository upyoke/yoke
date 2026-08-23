"""Frozen-view and accessor contracts for universal hook ordering."""

from __future__ import annotations

import unittest

from yoke_contracts.hook_runner.hook_ordering import (
    HOOK_ORDERING,
    event_types,
    matchers_for,
    ordered_pipeline_for,
)


class TestRegistryShape(unittest.TestCase):
    def test_TC_event_types_includes_required(self):
        types = event_types()
        for required in (
            "PreToolUse",
            "PostToolUse",
            "PermissionRequest",
            "SessionStart",
            "UserPromptSubmit",
            "Stop",
        ):
            self.assertIn(required, types)

    def test_TC_unknown_event_returns_empty_list(self):
        self.assertEqual(ordered_pipeline_for("DoesNotExist"), [])

    def test_TC_unknown_matcher_falls_back_to_default(self):
        chain = ordered_pipeline_for("PostToolUse", "TotallyMadeUp")
        expected = ordered_pipeline_for("PostToolUse", "Edit")
        self.assertEqual(chain, expected)

    def test_TC_pretooluse_unknown_matcher_returns_empty_when_no_default(self):
        chain = ordered_pipeline_for("PreToolUse", "TotallyMadeUp")
        self.assertEqual(chain, [])

    def test_TC_returned_list_is_fresh(self):
        chain1 = ordered_pipeline_for("PreToolUse", "Bash")
        chain2 = ordered_pipeline_for("PreToolUse", "Bash")
        chain1.append("mutated")
        self.assertNotIn("mutated", chain2)

    def test_TC_matchers_for_pretooluse_lists_all(self):
        matchers = matchers_for("PreToolUse")
        for required in ("Bash", "Edit", "Write", "Read", "Monitor"):
            self.assertIn(required, matchers)

    def test_TC_matchers_for_unknown_returns_empty(self):
        self.assertEqual(matchers_for("DoesNotExist"), [])

    def test_TC_hook_ordering_view_is_read_only(self):
        with self.assertRaises(TypeError):
            HOOK_ORDERING["PreToolUse"]["Bash"] = ()  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
