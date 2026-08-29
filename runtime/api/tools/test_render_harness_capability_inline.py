"""Tests for yoke_core.tools.render_harness_capability_inline."""

from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from yoke_contracts.harness_wake_capability import (
    HARNESS_WAKE_CAPABILITIES,
    wake_capability_for_harness,
)
from yoke_core.tools import render_harness_capability_inline as rhc


BEGIN = rhc.BEGIN_MARKER
END = rhc.END_MARKER


def _seed(root: pathlib.Path, files: dict[str, str]) -> None:
    for rel_path, contents in files.items():
        abs_path = root / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(contents, encoding="utf-8")


def _wrapped(body: str = "") -> str:
    return f"# Doc\n\nIntro.\n\n{BEGIN}\n{body}{END}\n\nTrailer.\n"


class WakeCapabilityContractTests(unittest.TestCase):
    def test_measured_harnesses_carry_evidence(self) -> None:
        for harness_id, cap in HARNESS_WAKE_CAPABILITIES.items():
            with self.subTest(harness=harness_id):
                self.assertTrue(
                    cap.evidence.strip(),
                    "a capability claim without evidence is the shape this "
                    "contract replaces",
                )
                self.assertIn(
                    cap.idle_wake, ("supported", "none", "unverified"),
                )
                self.assertIn(
                    cap.timer_wake, ("supported", "none", "unverified"),
                )

    def test_supported_wake_names_its_primitive(self) -> None:
        for harness_id, cap in HARNESS_WAKE_CAPABILITIES.items():
            with self.subTest(harness=harness_id):
                if cap.idle_wake == "supported":
                    self.assertTrue(cap.idle_wake_mechanism)
                if cap.timer_wake == "supported":
                    self.assertTrue(cap.timer_wake_mechanism)

    def test_probed_answers_match_the_measurements(self) -> None:
        cursor = HARNESS_WAKE_CAPABILITIES["cursor"]
        self.assertEqual(cursor.idle_wake, "supported")
        self.assertEqual(cursor.idle_wake_mechanism, "notify_on_output")
        self.assertEqual(cursor.timer_wake, "none")

        codex = HARNESS_WAKE_CAPABILITIES["codex"]
        self.assertEqual(codex.idle_wake, "none")
        self.assertEqual(codex.timer_wake, "none")

    def test_unknown_harness_is_unverified_not_a_guess(self) -> None:
        cap = wake_capability_for_harness("some-new-harness")
        self.assertEqual(cap.idle_wake, "unverified")
        self.assertEqual(cap.timer_wake, "unverified")
        self.assertEqual(cap.verified_on_surface, "")
        self.assertIn("some-new-harness", cap.evidence)


class BlockRenderTests(unittest.TestCase):
    def test_render_fills_every_inventory_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _seed(root, {path: _wrapped() for path in rhc.INVENTORY})

            with mock.patch(
                "yoke_core.tools.generated_block_render."
                "assert_target_under_session_work_authority",
            ):
                result = rhc.render(root)

            self.assertEqual(len(result.changed), len(rhc.INVENTORY))
            for path in rhc.INVENTORY:
                body = (root / path).read_text(encoding="utf-8")
                self.assertIn("notify_on_output", body)
                self.assertIn(rhc.MANIFEST_FIELD, body)

    def test_table_and_compact_surfaces_get_different_bodies(self) -> None:
        table = rhc.content_for_path(rhc.TABLE_SURFACES[0])
        compact = rhc.content_for_path(rhc.COMPACT_SURFACES[0])
        self.assertIn("| Harness |", table)
        self.assertIn("Evidence behind each row:", table)
        self.assertNotIn("| Harness |", compact)

    def test_check_mode_reports_drift_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _seed(root, {path: _wrapped() for path in rhc.INVENTORY})

            result = rhc.render(root, check=True)

            self.assertEqual(len(result.changed), len(rhc.INVENTORY))
            for path in rhc.INVENTORY:
                self.assertEqual(
                    (root / path).read_text(encoding="utf-8"), _wrapped(),
                )

    def test_rendered_surface_is_stable_on_repeat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _seed(root, {path: _wrapped() for path in rhc.INVENTORY})
            with mock.patch(
                "yoke_core.tools.generated_block_render."
                "assert_target_under_session_work_authority",
            ):
                rhc.render(root)
                second = rhc.render(root, check=True)
            self.assertEqual(second.changed, ())


class UncitedClaimScanTests(unittest.TestCase):
    def _scan_one(self, line: str) -> tuple[str, ...]:
        surface = rhc.CITATION_SCAN_SURFACES[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _seed(root, {surface: f"# Doc\n\n{line}\n"})
            return rhc.uncited_capability_claims(root)

    def test_uncited_capability_claim_is_reported(self) -> None:
        findings = self._scan_one("Codex has no Monitor primitive.")
        self.assertEqual(len(findings), 1)
        self.assertIn("Codex has no Monitor primitive", findings[0])

    def test_claim_naming_the_manifest_field_passes(self) -> None:
        findings = self._scan_one(
            "This hook is Claude-only because codex records "
            "`agent_wake.idle_wake = none`; it has no Monitor call to hint on."
        )
        self.assertEqual(findings, ())

    def test_using_a_primitive_is_not_a_capability_claim(self) -> None:
        findings = self._scan_one(
            "Arm a standing `Monitor` on a fleet-delta probe and never poll "
            "the capture yourself."
        )
        self.assertEqual(findings, ())

    def test_claim_inside_a_generated_block_is_not_reported(self) -> None:
        surface = rhc.CITATION_SCAN_SURFACES[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _seed(
                root,
                {surface: _wrapped("codex has no Monitor primitive.\n")},
            )
            self.assertEqual(rhc.uncited_capability_claims(root), ())

    def test_summary_names_the_repair(self) -> None:
        summary = rhc.format_uncited_summary(("docs/a.md:3: claim",))
        self.assertIn("docs/a.md:3", summary)
        self.assertIn(rhc.REPAIR_COMMAND, summary)
        self.assertEqual(rhc.format_uncited_summary(()), "")


class LiveTreeTests(unittest.TestCase):
    """The shipped tree is the surface the contract exists to protect."""

    def _repo_root(self) -> pathlib.Path:
        return pathlib.Path(__file__).resolve().parents[3]

    def test_shipped_surfaces_render_clean_and_cite_their_claims(self) -> None:
        root = self._repo_root()
        if not (root / rhc.INVENTORY[0]).exists():
            self.skipTest("not a Yoke source checkout")

        result = rhc.render(root, check=True)
        self.assertEqual(
            result.changed, (), rhc.format_render_drift(result, check=True),
        )
        findings = rhc.uncited_capability_claims(root)
        self.assertEqual(
            findings, (), rhc.format_uncited_summary(findings),
        )
        from yoke_core.tools import harness_continuation_coherence as hcc

        continuations = hcc.continuation_contract_contradictions(root)
        self.assertEqual(
            continuations, (), hcc.format_continuation_summary(continuations),
        )

    def test_manifests_carry_the_contract_answers(self) -> None:
        import json

        root = self._repo_root()
        for harness_id, cap in HARNESS_WAKE_CAPABILITIES.items():
            path = root / "runtime" / "harness" / _dir_for(harness_id) / (
                "manifest.json"
            )
            if not path.exists():
                self.skipTest(f"no manifest for {harness_id}")
            payload = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(harness=harness_id):
                self.assertEqual(
                    payload["agent_wake"]["idle_wake"], cap.idle_wake,
                )
                self.assertEqual(
                    payload["agent_wake"]["idle_wake_mechanism"],
                    cap.idle_wake_mechanism,
                )


def _dir_for(harness_id: str) -> str:
    return {"claude-code": "claude"}.get(harness_id, harness_id)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
