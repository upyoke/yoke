"""Coverage for the widened ``DEFAULT_REMINDER`` in ``hint_monitor_relay``.

The reminder is the positive-side counterpart to the
``lint_long_command_polling`` deny rules. The ACs require the prose
to mirror what the deny side now catches: widened peek verbs, the
``Bash(run_in_background)`` waiter shapes, and the
``/private/tmp/claude-...`` capture-file class.

These tests assert the reminder content, that ``DEFAULT_REMINDER``
remains the single source of truth (no other live module redefines
the canonical wording), and that the ``<system-reminder>`` envelope
shape is preserved.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from yoke_core.domain.hint_monitor_relay import (
    DEFAULT_REMINDER,
    resolve_reminder_text,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_SOURCE_ROOT = REPO_ROOT / "packages" / "yoke-core" / "src"


class TestDefaultReminderContent(unittest.TestCase):
    """The widened reminder mirrors the deny-side coverage."""

    def test_widened_peek_verb_enumeration_present(self) -> None:
        # Full canonical verb list present in the resolved text.
        text = resolve_reminder_text()
        self.assertIn(
            "tail/head/cat/wc/grep/egrep/fgrep/rg/ls/awk/sed/less/more/file/stat/nl/cut/sort/uniq",
            text,
        )

    def test_legacy_three_verb_phrasing_replaced(self) -> None:
        # The old "(tail/head/cat) while the owning command is
        # running" wording must be removed (replacement, not addition).
        text = resolve_reminder_text()
        self.assertNotIn(
            "(tail/head/cat) while the owning command is running",
            text,
        )

    def test_bg_waiter_prohibition_present(self) -> None:
        # The four waiter shapes are named.
        text = resolve_reminder_text()
        self.assertIn("Bash(run_in_background)", text)
        self.assertIn("tail -f <capture>", text)
        self.assertIn("sleep N && tail/cat <capture>", text)
        self.assertIn("while [ ! -f <sentinel> ]; do sleep; done", text)
        self.assertIn("watch_tail <capture>", text)
        self.assertIn("armed Monitor IS the waiter", text)

    def test_private_tmp_claude_path_called_out(self) -> None:
        # AC-23.
        text = resolve_reminder_text()
        self.assertIn("/private/tmp/claude-", text)
        # And the prose links it to the existing peek/waiter rules.
        self.assertIn("peek", text)
        self.assertIn("waiter", text)
        self.assertNotIn("pgrep -f <pattern>", text)

    def test_envelope_shape_preserved(self) -> None:
        # AC-25 (envelope half).
        text = resolve_reminder_text()
        self.assertTrue(text.startswith("<system-reminder>"))
        self.assertTrue(text.rstrip().endswith("</system-reminder>"))
        # No nested envelopes.
        self.assertEqual(text.count("<system-reminder>"), 1)
        self.assertEqual(text.count("</system-reminder>"), 1)


class TestReminderModuleSize(unittest.TestCase):
    """AC-25 (size half): hint_monitor_relay.py stays ≤200 lines."""

    def test_module_size_under_cap(self) -> None:
        path = PACKAGE_SOURCE_ROOT / "yoke_core" / "domain" / "hint_monitor_relay.py"
        line_count = sum(1 for _ in path.read_text(encoding="utf-8").splitlines())
        self.assertLessEqual(line_count, 200)


class TestReminderSingleSourceOfTruth(unittest.TestCase):
    """AC-24: ``DEFAULT_REMINDER`` is the only canonical reminder source.

    A grep for the ``"Avoid repeated peeks at the capture file"`` substring across
    ``packages/yoke-core/src`` returns exactly one hit (the canonical
    constant in ``hint_monitor_relay.py``).
    """

    def test_only_one_canonical_definition(self) -> None:
        # The substring is an exact match against the widened reminder
        # text. Only the canonical module should carry it. Skip __pycache__
        # (bytecode caches contain the source-literal verbatim) and this
        # test file itself.
        try:
            output = subprocess.run(
                [
                    "grep",
                    "-r",
                    "--exclude-dir=__pycache__",
                    "-l",
                    "--exclude-dir=__pycache__",
                    "Avoid repeated peeks at the capture file",
                    str(PACKAGE_SOURCE_ROOT),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            self.skipTest("grep not available on this platform")
        if output.returncode not in (0, 1):
            self.fail(
                f"grep failed: rc={output.returncode} stderr={output.stderr}"
            )
        hits = [
            line.strip()
            for line in output.stdout.splitlines()
            if line.strip()
        ]
        hits = [
            h for h in hits if not h.endswith("test_hint_monitor_relay.py")
        ]
        self.assertEqual(len(hits), 1, f"expected 1 hit, got: {hits}")
        self.assertTrue(hits[0].endswith("hint_monitor_relay.py"))


class TestDefaultReminderConstantParity(unittest.TestCase):
    """``DEFAULT_REMINDER`` and ``resolve_reminder_text()`` agree without override."""

    def test_default_resolves_when_no_override(self) -> None:
        text = resolve_reminder_text()
        # If no override is configured the resolved text equals the
        # constant (the override branch returns the override; the no-
        # override branch returns the constant).
        self.assertTrue(
            text == DEFAULT_REMINDER
            or text.strip() == DEFAULT_REMINDER.strip()
        )


if __name__ == "__main__":
    unittest.main()
