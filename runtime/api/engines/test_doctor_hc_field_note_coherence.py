"""Tests for ``HC-field-note-coherence``.

Verifies positive (clean tree → PASS), drift fixture (stale marker file →
FAIL), and consumer-violation fixture (synthetic copy of directive text
in a non-canonical site → FAIL). Also asserts the contract tuples are
non-empty and self-skip is graceful when prerequisites are missing.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from yoke_core.engines.doctor_hc_field_note_coherence import (
    CANONICAL_COMMAND,
    CANONICAL_MODULE,
    HC_NAME,
    HELPER_MODULE,
    HELPER_SYMBOL,
    IMPORTING_CONSUMERS,
    PACKET_SEED_CONSUMERS,
    hc_field_note_coherence,
    scan_importing_consumers,
    scan_packet_seeds,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _run_hc() -> RecordCollector:
    rec = RecordCollector()
    hc_field_note_coherence(
        conn=None, args=DoctorArgs(project="yoke"), rec=rec,
    )
    return rec


def test_contract_tuples_are_non_empty() -> None:
    """Regression guard: clearing the enforcement scope would silently PASS."""
    assert len(IMPORTING_CONSUMERS) >= 5
    # 5 hand-named consumers plus the lint-denial importer set.
    assert len(IMPORTING_CONSUMERS) == 5 + 22
    assert len(PACKET_SEED_CONSUMERS) == 2


def test_contract_paths_exist_on_live_tree() -> None:
    """Regression guard against stale paths silently shrinking scan scope."""
    repo_root = _project_root()
    named_paths = IMPORTING_CONSUMERS + PACKET_SEED_CONSUMERS
    missing = [p for p in named_paths if not (repo_root / p).is_file()]
    assert missing == []


def test_doctor_entry_passes_on_clean_live_tree() -> None:
    """End-to-end: clean live tree PASSes the HC."""
    rec = _run_hc()
    assert rec.results, "doctor HC produced no result"
    result = rec.results[-1]
    assert result.check_id == HC_NAME
    assert result.result == "PASS", (
        f"expected PASS, got {result.result}: {result.detail}"
    )


def test_named_consumers_import_canonical_on_live_tree() -> None:
    """Every importing consumer reads from the canonical module on disk."""
    missing = scan_importing_consumers(_project_root())
    assert missing == [], (
        f"importing consumers missing canonical import: {missing!r}"
    )


def test_packet_seeds_carry_canonical_command_on_live_tree() -> None:
    """Both packet seeds carry the canonical field-note command verbatim."""
    missing = scan_packet_seeds(_project_root())
    assert missing == [], (
        f"packet seeds missing `{CANONICAL_COMMAND}`: {missing!r}"
    )


def test_consumer_violation_fixture_detected(tmp_path: Path) -> None:
    """A synthetic consumer that omits the canonical import FAILs detection."""
    fake_rel = "runtime/api/domain/lint_synthetic_violation.py"
    fake_path = tmp_path / fake_rel
    fake_path.parent.mkdir(parents=True)
    # Carries the canonical command as a string literal but NO import —
    # this is the exact drift class the HC catches.
    fake_path.write_text(
        '"""Synthetic test-fixture lint that bypasses the helper."""\n'
        "DENY = 'use `yoke ouroboros field-note append --kind ...`'\n"
    )
    missing = scan_importing_consumers(tmp_path, consumers=(fake_rel,))
    assert missing == [fake_rel]


def test_compliant_fixture_passes(tmp_path: Path) -> None:
    """A fixture importing from the canonical module is not flagged."""
    fake_rel = "runtime/api/domain/lint_synthetic_clean.py"
    fake_path = tmp_path / fake_rel
    fake_path.parent.mkdir(parents=True)
    fake_path.write_text(
        f"from {CANONICAL_MODULE} import FOOTER\n"
        "DENY = FOOTER\n"
    )
    missing = scan_importing_consumers(tmp_path, consumers=(fake_rel,))
    assert missing == []


def test_helper_indirection_fixture_passes(tmp_path: Path) -> None:
    """Importing the denial helper (which re-exports FOOTER) is sufficient."""
    fake_rel = "runtime/api/domain/lint_synthetic_indirection.py"
    fake_path = tmp_path / fake_rel
    fake_path.parent.mkdir(parents=True)
    fake_path.write_text(
        f"from {HELPER_MODULE} import {HELPER_SYMBOL}\n"
        f"def reason(t): return {HELPER_SYMBOL}(t, rule_id='x')\n"
    )
    missing = scan_importing_consumers(tmp_path, consumers=(fake_rel,))
    assert missing == []


def test_missing_consumer_file_skips_silently(tmp_path: Path) -> None:
    """Absent files do not register as violations (graceful degrade)."""
    missing = scan_importing_consumers(
        tmp_path, consumers=("runtime/api/domain/nonexistent.py",),
    )
    assert missing == []


def test_packet_seed_missing_command_detected(tmp_path: Path) -> None:
    """A packet seed that loses the canonical command FAILs detection."""
    fake_rel = (
        "packages/yoke-core/src/yoke_core/domain/"
        "schema_api_context_fake.py"
    )
    fake_path = tmp_path / fake_rel
    fake_path.parent.mkdir(parents=True)
    fake_path.write_text(
        '"""Synthetic packet seed that lost its field-note teaching."""\n'
        "ENTRIES = ({'topic': 'core', 'purpose': 'unrelated'},)\n"
    )
    missing = scan_packet_seeds(tmp_path, seeds=(fake_rel,))
    assert missing == [fake_rel]


def test_drift_fixture_fails(monkeypatch, tmp_path: Path) -> None:
    """A renderer reporting drift FAILs the HC; remediation prompt cited."""
    from yoke_core.engines import doctor_hc_field_note_coherence as mod

    class _Outcome:
        def __init__(self, path: str) -> None:
            self.path = path

    class _DriftResult:
        changed = (_Outcome("docs/OVERVIEW.md"),)
        orphan_marker_errors: tuple = ()

    class _StubRenderer:
        @staticmethod
        def render(target_root, *, check: bool):  # noqa: ARG004
            return _DriftResult()

    def _stub_check(repo_root: Path) -> tuple:
        return (None, ["docs/OVERVIEW.md"], [])

    monkeypatch.setattr(mod, "_run_renderer_check", _stub_check)
    rec = RecordCollector()
    mod.hc_field_note_coherence(
        conn=None, args=DoctorArgs(project="yoke"), rec=rec,
    )
    result = rec.results[-1]
    assert result.check_id == HC_NAME
    assert result.result == "FAIL"
    assert "render_field_note_inline" in result.detail
    assert "docs/OVERVIEW.md" in result.detail


def test_renderer_unavailable_self_skips(monkeypatch) -> None:
    """Missing canonical surface degrades to PASS with a skip rationale."""
    from yoke_core.engines import doctor_hc_field_note_coherence as mod

    monkeypatch.setattr(
        mod, "_run_renderer_check",
        lambda _root: ("renderer not importable (stub) — skipping", [], []),
    )
    rec = RecordCollector()
    mod.hc_field_note_coherence(
        conn=None, args=DoctorArgs(project="yoke"), rec=rec,
    )
    result = rec.results[-1]
    assert result.check_id == HC_NAME
    assert result.result == "PASS"
    assert "skipping" in result.detail
