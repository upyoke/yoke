"""observe — enriched context coverage.

Split out of ``test_observe.py`` to keep authored files under the 350-line
limit.
"""

from __future__ import annotations

import json
import unittest

from yoke_core.domain.observe import (
    build_envelope,
    detect_anomalies,
    parse_hook_event,
)


class TestEnrichedContext(unittest.TestCase):
    """AC-4: context.detail includes tool_input, tool_response_preview, error,
    attribution_source, hook_event."""

    def test_TC_bash_context_has_enriched_fields(self):
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo hello world"},
            "tool_response": {"content": "hello world"},
        }
        rec = parse_hook_event(
            data,
            session_id="sess_004",
            hook_event="PostToolUse",
            attribution_source="explicit_bash_ref",
        )
        detect_anomalies(rec)
        envelope = build_envelope(rec)

        ctx = envelope["context"]["detail"]
        self.assertEqual(ctx["tool_name"], "Bash")
        self.assertEqual(ctx["tool_input"], "echo hello world")
        self.assertEqual(ctx["tool_response_preview"], "hello world")
        self.assertEqual(ctx["attribution_source"], "explicit_bash_ref")
        self.assertEqual(ctx["hook_event"], "PostToolUse")
        # Old key should not exist
        self.assertNotIn("command", ctx)
        self.assertNotIn("response_preview", ctx)

    def test_TC_file_op_context_has_tool_input(self):
        data = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/some/path.py"},
            "tool_response": {"content": "file content"},
        }
        rec = parse_hook_event(
            data,
            session_id="sess_005",
            hook_event="PostToolUse",
        )
        detect_anomalies(rec)
        envelope = build_envelope(rec)

        ctx = envelope["context"]["detail"]
        self.assertEqual(ctx["tool_input"], "/some/path.py")

    def test_TC_error_in_context(self):
        data = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/tmp/test.py"},
            "tool_response": {},
            "error": "String to replace not found",
        }
        rec = parse_hook_event(
            data,
            session_id="sess_006",
            hook_event="PostToolUseFailure",
        )
        detect_anomalies(rec)
        envelope = build_envelope(rec)

        ctx = envelope["context"]["detail"]
        self.assertIn("error", ctx)
        self.assertEqual(ctx["error"], "String to replace not found")

    def test_TC_decision_metadata_placeholder(self):
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "tool_response": {"content": "ok"},
            "permissionDecision": {"allow": True},
        }
        rec = parse_hook_event(
            data,
            session_id="sess_007",
            hook_event="PostToolUse",
        )
        detect_anomalies(rec)
        envelope = build_envelope(rec)

        ctx = envelope["context"]["detail"]
        self.assertIn("decision_metadata", ctx)
        self.assertEqual(ctx["decision_metadata"], {})

    def test_TC_context_4kb_cap(self):
        long_cmd = "x" * 5000
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": long_cmd},
            "tool_response": {"content": "y" * 3000},
            "error": "z" * 3000,
        }
        rec = parse_hook_event(
            data,
            session_id="sess_008",
            hook_event="PostToolUseFailure",
        )
        detect_anomalies(rec)
        envelope = build_envelope(rec)

        ctx = envelope["context"]["detail"]
        ctx_json = json.dumps(ctx, separators=(",", ":"))
        # After cap, tool_input should be truncated
        self.assertLessEqual(len(ctx.get("tool_input", "")), 2048)

    def test_TC_post_tool_payload_agent_type_becomes_actor_role(self):
        data = {
            "tool_name": "Bash",
            "agent_type": "engineer",
            "tool_input": {"command": "echo hello"},
            "tool_response": {"content": "hello"},
        }
        rec = parse_hook_event(
            data,
            session_id="sess_009",
            hook_event="PostToolUse",
        )
        detect_anomalies(rec)
        envelope = build_envelope(rec)

        self.assertEqual(envelope["agent"], "engineer")
        self.assertEqual(
            envelope["context"]["detail"]["actor_role"], "engineer"
        )

    def test_TC_pre_tool_payload_agent_type_becomes_actor_role(self):
        from yoke_core.domain.observe_pre import parse_pre_event

        envelope = parse_pre_event({
            "tool_name": "Bash",
            "tool_use_id": "tu_pre_actor",
            "session_id": "sess_010",
            "agent_type": "tester",
            "tool_input": {"command": "python3 -m pytest"},
        })

        self.assertIsNotNone(envelope)
        self.assertEqual(envelope["agent"], "tester")
        self.assertEqual(
            envelope["context"]["detail"]["actor_role"], "tester"
        )


if __name__ == "__main__":
    unittest.main()
