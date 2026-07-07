"""Tests for the universal policy pipeline.

Asserts:
- ``tool_kind_for`` translates each documented native tool name.
- ``build_tool_event_record`` produces the right ``changed_paths`` /
  ``command`` / ``patch_body`` for each ``tool_kind``.
- ``dispatch`` walks the ordered chain, short-circuits on ``deny``,
  and never raises on a buggy policy module.
"""

from __future__ import annotations

import sys
import types
import unittest
from typing import Optional
from unittest import mock

from yoke_core.domain import harness_policy_pipeline as pipeline
from yoke_core.domain.harness_policy_pipeline import (
    PipelineResult,
    PolicyDecision,
    build_tool_event_record,
    dispatch,
    tool_kind_for,
)
from yoke_core.domain.observe_normalization import (
    TOOL_KIND_APPLY_PATCH,
    TOOL_KIND_BASH,
    TOOL_KIND_EDIT,
    TOOL_KIND_WRITE,
    ToolEventRecord,
)


class TestToolKindFor(unittest.TestCase):
    def test_TC_known_tool_names(self):
        self.assertEqual(tool_kind_for("Bash"), TOOL_KIND_BASH)
        self.assertEqual(tool_kind_for("shell"), TOOL_KIND_BASH)
        self.assertEqual(tool_kind_for("Write"), TOOL_KIND_WRITE)
        self.assertEqual(tool_kind_for("Edit"), TOOL_KIND_EDIT)
        self.assertEqual(tool_kind_for("apply_patch"), TOOL_KIND_APPLY_PATCH)
        self.assertEqual(tool_kind_for("ApplyPatch"), TOOL_KIND_APPLY_PATCH)

    def test_TC_unknown_tool_name_returns_none(self):
        self.assertIsNone(tool_kind_for("Read"))
        self.assertIsNone(tool_kind_for("Monitor"))
        self.assertIsNone(tool_kind_for("ScheduleWakeup"))

    def test_TC_empty_tool_name_returns_none(self):
        self.assertIsNone(tool_kind_for(""))


class TestBuildToolEventRecord(unittest.TestCase):
    def test_TC_bash_record(self):
        rec = build_tool_event_record(
            tool_name="Bash",
            tool_input={"command": "ls"},
            session_id="sess_a",
        )
        self.assertIsNotNone(rec)
        assert rec is not None  # for type checkers
        self.assertEqual(rec.tool_kind, TOOL_KIND_BASH)
        self.assertEqual(rec.command, "ls")
        self.assertEqual(rec.changed_paths, [])
        self.assertEqual(rec.session_id, "sess_a")

    def test_TC_write_record_has_single_changed_path(self):
        rec = build_tool_event_record(
            tool_name="Write",
            tool_input={"file_path": "/tmp/new.py"},
        )
        assert rec is not None
        self.assertEqual(rec.tool_kind, TOOL_KIND_WRITE)
        self.assertEqual(rec.changed_paths, ["/tmp/new.py"])
        self.assertEqual(rec.command, "")

    def test_TC_edit_record_has_single_changed_path(self):
        rec = build_tool_event_record(
            tool_name="Edit",
            tool_input={"file_path": "/tmp/edit.py"},
        )
        assert rec is not None
        self.assertEqual(rec.tool_kind, TOOL_KIND_EDIT)
        self.assertEqual(rec.changed_paths, ["/tmp/edit.py"])

    def test_TC_apply_patch_parses_changed_paths_under_input_key(self):
        body = (
            "*** Begin Patch\n"
            "*** Add File: a.py\n"
            "+x\n"
            "*** Update File: b.py\n"
            "+y\n"
            "*** End Patch\n"
        )
        rec = build_tool_event_record(
            tool_name="apply_patch",
            tool_input={"input": body},
        )
        assert rec is not None
        self.assertEqual(rec.tool_kind, TOOL_KIND_APPLY_PATCH)
        self.assertEqual(rec.patch_body, body)
        self.assertIn("a.py", rec.changed_paths)
        self.assertIn("b.py", rec.changed_paths)

    def test_TC_apply_patch_falls_back_to_patch_key(self):
        body = "*** Add File: only.py\n"
        rec = build_tool_event_record(
            tool_name="apply_patch",
            tool_input={"patch": body},
        )
        assert rec is not None
        self.assertEqual(rec.changed_paths, ["only.py"])

    def test_TC_apply_patch_with_empty_envelope_has_empty_paths(self):
        rec = build_tool_event_record(
            tool_name="apply_patch",
            tool_input={"input": ""},
        )
        assert rec is not None
        self.assertEqual(rec.changed_paths, [])
        self.assertEqual(rec.patch_body, "")

    def test_TC_unknown_tool_returns_none(self):
        self.assertIsNone(build_tool_event_record(tool_name="Read", tool_input={}))

    def test_TC_missing_tool_input_does_not_raise(self):
        rec = build_tool_event_record(tool_name="Bash", tool_input=None)
        assert rec is not None
        self.assertEqual(rec.command, "")
        self.assertEqual(rec.changed_paths, [])

    def test_TC_record_preserves_session_context(self):
        rec = build_tool_event_record(
            tool_name="Bash",
            tool_input={"command": "true"},
            session_id="sess_xyz",
            tool_use_id="tu_42",
            turn_id="turn_1",
            cwd="/tmp/work",
            project_dir="/tmp/proj",
        )
        assert rec is not None
        self.assertEqual(rec.session_id, "sess_xyz")
        self.assertEqual(rec.tool_use_id, "tu_42")
        self.assertEqual(rec.turn_id, "turn_1")
        self.assertEqual(rec.cwd, "/tmp/work")
        self.assertEqual(rec.project_dir, "/tmp/proj")


class TestDispatch(unittest.TestCase):
    """Dispatcher: ordered chain walk, deny short-circuit, fail-open on raise."""

    def setUp(self) -> None:
        # Each test installs its own fake policy modules under unique
        # names; teardown removes them so other tests aren't affected.
        self._installed_modules: list[str] = []

    def tearDown(self) -> None:
        for mod_id in self._installed_modules:
            sys.modules.pop(mod_id, None)

    def _install_fake_module(
        self,
        module_id: str,
        decision: Optional[PolicyDecision],
        *,
        raises: bool = False,
        no_hook: bool = False,
    ) -> None:
        """Inject a fake policy module into ``sys.modules``."""
        module = types.ModuleType(module_id)

        def decide_for_record(record: ToolEventRecord) -> Optional[PolicyDecision]:
            if raises:
                raise RuntimeError("policy module is buggy")
            return decision

        if not no_hook:
            module.decide_for_record = decide_for_record  # type: ignore[attr-defined]
        sys.modules[module_id] = module
        self._installed_modules.append(module_id)

    def test_TC_dispatch_unmodelled_kind_returns_empty(self):
        rec = ToolEventRecord(tool_kind="not_a_real_kind")
        result = dispatch(rec)
        self.assertIsInstance(result, PipelineResult)
        self.assertFalse(result.denied)
        self.assertEqual(result.decisions, [])

    def test_TC_dispatch_walks_chain_in_order(self):
        rec = ToolEventRecord(tool_kind=TOOL_KIND_BASH)
        recorded: list[str] = []

        def make_record_decide(label: str):
            def fn(_record: ToolEventRecord) -> Optional[PolicyDecision]:
                recorded.append(label)
                return PolicyDecision(outcome="allow", module=label)

            return fn

        # Patch the chain to two known module ids and install fakes for them.
        chain = ["fake.policy.first", "fake.policy.second"]
        self._install_fake_module("fake.policy.first", PolicyDecision(outcome="allow"))
        self._install_fake_module("fake.policy.second", PolicyDecision(outcome="allow"))
        # Override decide_for_record to record invocation order.
        sys.modules["fake.policy.first"].decide_for_record = make_record_decide(  # type: ignore[attr-defined]
            "first"
        )
        sys.modules["fake.policy.second"].decide_for_record = make_record_decide(  # type: ignore[attr-defined]
            "second"
        )

        with mock.patch.object(
            pipeline, "ordered_pipeline_for", return_value=chain
        ):
            result = dispatch(rec)

        self.assertEqual(recorded, ["first", "second"])
        self.assertEqual(len(result.decisions), 2)
        self.assertFalse(result.denied)

    def test_TC_dispatch_short_circuits_on_deny(self):
        rec = ToolEventRecord(tool_kind=TOOL_KIND_BASH)
        chain = ["fake.policy.allow", "fake.policy.deny", "fake.policy.never"]
        self._install_fake_module(
            "fake.policy.allow", PolicyDecision(outcome="allow")
        )
        self._install_fake_module(
            "fake.policy.deny",
            PolicyDecision(outcome="deny", reason="not allowed"),
        )

        invoked: list[str] = []

        def never_called(_record: ToolEventRecord) -> Optional[PolicyDecision]:
            invoked.append("never")
            return None

        never_module = types.ModuleType("fake.policy.never")
        never_module.decide_for_record = never_called  # type: ignore[attr-defined]
        sys.modules["fake.policy.never"] = never_module
        self._installed_modules.append("fake.policy.never")

        with mock.patch.object(
            pipeline, "ordered_pipeline_for", return_value=chain
        ):
            result = dispatch(rec)

        self.assertTrue(result.denied)
        self.assertEqual(result.deny_reason, "not allowed")
        self.assertEqual(result.deny_module, "fake.policy.deny")
        self.assertEqual(invoked, [])  # never_called was never invoked

    def test_TC_dispatch_skips_modules_without_hook(self):
        rec = ToolEventRecord(tool_kind=TOOL_KIND_BASH)
        chain = ["fake.policy.no_hook", "fake.policy.has_hook"]
        self._install_fake_module(
            "fake.policy.no_hook", None, no_hook=True
        )
        self._install_fake_module(
            "fake.policy.has_hook",
            PolicyDecision(outcome="allow"),
        )

        with mock.patch.object(
            pipeline, "ordered_pipeline_for", return_value=chain
        ):
            result = dispatch(rec)

        # Only the module with the hook produced a decision.
        self.assertEqual(len(result.decisions), 1)
        self.assertEqual(result.decisions[0].module, "fake.policy.has_hook")

    def test_TC_dispatch_skips_unimportable_modules(self):
        rec = ToolEventRecord(tool_kind=TOOL_KIND_BASH)
        chain = ["definitely.not.a.real.module"]

        with mock.patch.object(
            pipeline, "ordered_pipeline_for", return_value=chain
        ):
            result = dispatch(rec)

        self.assertEqual(result.decisions, [])
        self.assertFalse(result.denied)

    def test_TC_dispatch_records_error_when_module_raises(self):
        rec = ToolEventRecord(tool_kind=TOOL_KIND_BASH)
        chain = ["fake.policy.raiser", "fake.policy.allows"]
        self._install_fake_module(
            "fake.policy.raiser", None, raises=True
        )
        self._install_fake_module(
            "fake.policy.allows", PolicyDecision(outcome="allow")
        )

        with mock.patch.object(
            pipeline, "ordered_pipeline_for", return_value=chain
        ):
            result = dispatch(rec)

        # First module errored, but pipeline continued (fail-open).
        self.assertEqual(len(result.decisions), 2)
        self.assertEqual(result.decisions[0].outcome, "error")
        self.assertEqual(result.decisions[0].module, "fake.policy.raiser")
        self.assertEqual(result.decisions[1].outcome, "allow")
        self.assertFalse(result.denied)

    def test_TC_dispatch_uses_apply_patch_matcher(self):
        rec = ToolEventRecord(tool_kind=TOOL_KIND_APPLY_PATCH)
        seen_args: list[tuple] = []

        def fake_chain(event: str, matcher: str = "_default") -> list[str]:
            seen_args.append((event, matcher))
            return []

        with mock.patch.object(
            pipeline, "ordered_pipeline_for", side_effect=fake_chain
        ):
            dispatch(rec)

        self.assertEqual(seen_args, [("PreToolUse", "apply_patch")])

    def test_TC_first_deny_returns_none_when_no_deny(self):
        result = PipelineResult(
            decisions=[
                PolicyDecision(outcome="allow", module="m1"),
                PolicyDecision(outcome="warn", reason="careful", module="m2"),
            ]
        )
        self.assertIsNone(result.first_deny())

    def test_TC_first_deny_returns_first_match(self):
        result = PipelineResult(
            decisions=[
                PolicyDecision(outcome="allow", module="m1"),
                PolicyDecision(outcome="deny", reason="r1", module="m2"),
                PolicyDecision(outcome="deny", reason="r2", module="m3"),
            ]
        )
        decision = result.first_deny()
        assert decision is not None
        self.assertEqual(decision.module, "m2")
        self.assertEqual(decision.reason, "r1")


if __name__ == "__main__":
    unittest.main()
