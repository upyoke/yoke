"""Regression matrix for ``agents_render`` pipe-to-truncator shapes.

Two structurally-identical Bash shapes had different lint outcomes within
an hour of each other against the same machine: ``cd ... &&
python3 -m yoke_core.domain.agents_render render 2>&1 | head -30``
DENIED, while ``python3 -m yoke_core.domain.agents_render render 2>&1
| tail -30`` ALLOWED and wrote wrong-tree adapter files. The lint family
is present; the unevenness lived in the wrapping classifier's
``is_write_output_consumer_only`` allowance, which let mutating
registered adapters escape the deny path whenever a bare pipe-to-read
verb followed the call.

This sibling test file enumerates every pipe-to-truncator variant —
``| head``, ``| tail``, ``| head -N``, ``| tail -N``, ``2>&1 | head``,
``2>&1 | tail`` — with and without a leading ``cd ... &&`` or ``cd ...;``
clause, and confirms:

- Every mutating ``agents_render render`` variant denies with the
  canonical ``BLOCKED: registry-covered Yoke CLI wrapped with shell
  choreography.`` prefix and surfaces the ``agents.render.run`` function
  id.
- The read-shape counterpart ``agents_render check`` keeps the existing
  read-wrapping allowance under the same shapes.
"""

from __future__ import annotations

import unittest

from yoke_core.domain import lint_shell_quoted_function_payload as lint


_MUTATING_CMD = "python3 -m yoke_core.domain.agents_render render"
_READ_CMD = "python3 -m yoke_core.domain.agents_render check"
_BLOCKED_PREFIX = "BLOCKED: registry-covered Yoke CLI wrapped with shell choreography."
_WRITE_FN_ID = "agents.render.run"

_WRAPPING_VARIANTS = (
    "| head",
    "| head -30",
    "| tail",
    "| tail -30",
    "2>&1 | head",
    "2>&1 | head -30",
    "2>&1 | tail",
    "2>&1 | tail -30",
)

_LEADING_CLAUSES = (
    "",
    "cd /tmp && ",
    "cd /tmp ; ",
)


def _matrix(command: str):
    for leading in _LEADING_CLAUSES:
        for wrapping in _WRAPPING_VARIANTS:
            yield f"{leading}{command} {wrapping}", leading, wrapping


class TestAgentsRenderMutatingPipeVariants(unittest.TestCase):
    """Every mutating ``agents_render render`` pipe-to-truncator variant
    denies with the canonical prefix and function id (AC-1..AC-4)."""

    def test_every_variant_denies_with_canonical_prefix(self) -> None:
        for cmd, leading, wrapping in _matrix(_MUTATING_CMD):
            with self.subTest(leading=leading, wrapping=wrapping):
                reason = lint.evaluate_command(cmd)
                self.assertIsNotNone(
                    reason,
                    msg=f"expected DENY, got ALLOW for: {cmd}",
                )
                self.assertTrue(
                    reason.startswith(_BLOCKED_PREFIX),
                    msg=(
                        f"expected reason to start with {_BLOCKED_PREFIX!r}; "
                        f"got {reason!r} for: {cmd}"
                    ),
                )
                self.assertIn(_WRITE_FN_ID, reason, msg=cmd)

    def test_lint_outcome_uniform_across_separators(self) -> None:
        """AC-3: equivalent shapes differing only in `&&` vs `;` before
        the registered adapter command produce identical lint outcomes."""
        for wrapping in _WRAPPING_VARIANTS:
            cmd_amp = f"cd /tmp && {_MUTATING_CMD} {wrapping}"
            cmd_semi = f"cd /tmp ; {_MUTATING_CMD} {wrapping}"
            with self.subTest(wrapping=wrapping):
                reason_amp = lint.evaluate_command(cmd_amp)
                reason_semi = lint.evaluate_command(cmd_semi)
                self.assertIsNotNone(reason_amp, msg=cmd_amp)
                self.assertIsNotNone(reason_semi, msg=cmd_semi)
                self.assertEqual(
                    reason_amp.startswith(_BLOCKED_PREFIX),
                    reason_semi.startswith(_BLOCKED_PREFIX),
                    msg=f"prefix mismatch between '&&' and ';' for {wrapping}",
                )

    def test_lint_outcome_uniform_with_and_without_leading_cd(self) -> None:
        """AC-3 companion: the bare and ``cd ... &&``-prefixed shapes
        DENY uniformly."""
        for wrapping in _WRAPPING_VARIANTS:
            cmd_bare = f"{_MUTATING_CMD} {wrapping}"
            cmd_cd = f"cd /tmp && {_MUTATING_CMD} {wrapping}"
            with self.subTest(wrapping=wrapping):
                self.assertIsNotNone(
                    lint.evaluate_command(cmd_bare), msg=cmd_bare,
                )
                self.assertIsNotNone(
                    lint.evaluate_command(cmd_cd), msg=cmd_cd,
                )


class TestAgentsRenderReadShapeStillAllowed(unittest.TestCase):
    """AC-4 companion: the read-shape adapter ``agents_render check``
    retains the existing read-wrapping allowance under the same shapes
    that DENY for the mutating sibling."""

    def test_read_shape_with_read_wrapping_allowed(self) -> None:
        for cmd, leading, wrapping in _matrix(_READ_CMD):
            if leading.startswith("cd "):
                # Leading ``cd`` is upstream choreography and denies
                # regardless of the function's read shape — that is the
                # existing contract and not under test here.
                continue
            with self.subTest(leading=leading, wrapping=wrapping):
                self.assertIsNone(
                    lint.evaluate_command(cmd),
                    msg=f"expected ALLOW for read-shape: {cmd}",
                )


class TestForensicShapesFromYok1784(unittest.TestCase):
    """The two live commands from the YOK-1784 forensic record."""

    def test_leading_cd_head_denies(self) -> None:
        cmd = (
            "cd /Users/x/.worktrees/YOK-1788 && "
            "python3 -m yoke_core.domain.agents_render render "
            "2>&1 | head -30"
        )
        reason = lint.evaluate_command(cmd)
        self.assertIsNotNone(reason)
        self.assertTrue(reason.startswith(_BLOCKED_PREFIX))

    def test_direct_tail_denies(self) -> None:
        cmd = (
            "python3 -m yoke_core.domain.agents_render render "
            "2>&1 | tail -30"
        )
        reason = lint.evaluate_command(cmd)
        self.assertIsNotNone(reason)
        self.assertTrue(reason.startswith(_BLOCKED_PREFIX))
        self.assertIn(_WRITE_FN_ID, reason)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
