"""The pre-commit gate sequence, and the advisory that must not decide it.

``run()`` consults a fixed sequence of gates. The diverged-branch warning
advises the operator; only a gate's return code decides the commit. Asserting
that needs every gate stubbed — including the ones this module says nothing
about — because a live gate makes the verdict depend on whatever checkout the
suite runs in, and a real drift then arrives as a bare ``1 != 0`` naming
neither the gate nor the file.

Sibling of ``test_git_pre_commit.py``, which holds the per-gate coverage and is
at the authored-file line cap.
"""

from __future__ import annotations

import contextlib
import io
import unittest
from unittest import mock

from yoke_core.domain import git_pre_commit as mod


class TestDivergedWarningStillAdvisory(unittest.TestCase):
    """The diverged-branch warning advises; the gate return codes decide.

    Every gate ``run()`` consults is stubbed, including the ones this class
    says nothing about. Leaving any of them live makes the assertion depend on
    the state of whatever checkout the suite happens to run in: a real drift
    anywhere in the tree then surfaces here as a bare ``1 != 0`` naming
    neither the gate nor the file, which is how one such regression got
    misread as a pre-existing failure. Each stubbed gate is covered by its own
    tests elsewhere in this module.
    """

    #: Every gate ``run()`` consults, in call order. Stubbed to 0 unless the
    #: case under test overrides one.
    _GATES = (
        "_run_file_line_check_or_block",
        "_run_field_note_render_or_block",
        "_run_harness_capability_render_or_block",
        "_run_agent_render_check_or_block",
        "_run_worktree_status_check_or_block",
        "_run_path_claim_coverage_check_or_block",
    )

    def test_every_gate_run_consults_is_stubbed(self) -> None:
        """A gate added to ``run()`` without a stub here would go unnoticed.

        It would not fail loudly either: the new gate would run against the
        live checkout and this class would start reporting that tree's state
        as its own verdict.
        """
        import inspect

        source = inspect.getsource(mod.run)
        called = {
            name
            for name in dir(mod)
            if name.startswith("_run_") and f"{name}()" in source
        }
        self.assertEqual(called, set(self._GATES))

    def _run_with_patched_helpers(
        self,
        diverged: list[str],
        staged: list[str],
        file_line_rc: int,
    ) -> tuple[int, str]:
        sequence = iter([diverged, staged])

        def side_effect(_args):
            return next(sequence)

        rcs = dict.fromkeys(self._GATES, 0)
        rcs["_run_file_line_check_or_block"] = file_line_rc
        buf = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(mod, "_git_name_only", side_effect=side_effect)
            )
            for gate, rc_value in rcs.items():
                stack.enter_context(
                    mock.patch.object(mod, gate, return_value=rc_value)
                )
            stack.enter_context(mock.patch.object(mod.sys, "stderr", buf))
            rc = mod.run()
        return rc, buf.getvalue()

    def test_no_diverged_still_runs_file_line_check(self) -> None:
        rc, out = self._run_with_patched_helpers([], [], file_line_rc=0)
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_overlap_prints_warning_and_file_line_rc_wins(self) -> None:
        rc, out = self._run_with_patched_helpers(
            ["foo.py", "bar.py"], ["foo.py", "baz.py"], file_line_rc=0
        )
        self.assertEqual(rc, 0)
        self.assertIn("WARNING", out)
        self.assertIn("foo.py", out)

    def test_warning_prints_even_when_file_line_hard_fails(self) -> None:
        rc, out = self._run_with_patched_helpers(
            ["foo.py"], ["foo.py"], file_line_rc=1
        )
        self.assertEqual(rc, 1)
        self.assertIn("WARNING", out)
