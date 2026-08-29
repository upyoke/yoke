"""Tests for Codex continuation-contract teaching coherence."""

from __future__ import annotations

import pathlib
import tempfile
import unittest

from yoke_core.tools import harness_continuation_coherence as hcc


class ContinuationContractTests(unittest.TestCase):
    def test_codex_evidence_names_explicit_continuation(self) -> None:
        self.assertIn("codex", hcc.explicit_continuation_harnesses())

    def test_automatic_streaming_sentence_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "AGENTS.md").write_text(
                "Codex uses native PTY streaming and satisfies this "
                "automatically, because idle_wake is none.\n",
                encoding="utf-8",
            )
            findings = hcc.continuation_contract_contradictions(root)
        self.assertEqual(len(findings), 1)
        self.assertIn("AGENTS.md:1:", findings[0])
        summary = hcc.format_continuation_summary(findings)
        self.assertIn("write_stdin", summary)
        self.assertIn("AGENTS.md:1", summary)

    def test_explicit_continuation_teaching_is_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "AGENTS.md").write_text(
                "Codex has no idle-wake primitive; a long exec_command "
                "that outlives its yield returns a session_id that must "
                "be continued with write_stdin.\n",
                encoding="utf-8",
            )
            self.assertEqual(hcc.continuation_contract_contradictions(root), ())
        self.assertEqual(hcc.format_continuation_summary(()), "")
