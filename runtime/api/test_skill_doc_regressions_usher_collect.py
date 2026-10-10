"""Usher admission consumes the producer's scoped integration decision."""

from runtime.api.skill_doc_regressions_test_helpers import SKILLS, _read


def test_collect_reads_the_registered_integration_gate():
    text = _read(SKILLS / "usher" / "collect.md")
    assert "yoke items dependency list PREFIX-N --json" in text
    assert "result.integration_gate.evaluated" in text
    assert "is_blocked/blockers" in text
    assert "Any blocked item stops before computing merge order" in text


def test_collect_refuses_missing_gate_without_an_unscoped_fallback():
    text = _read(SKILLS / "usher" / "collect.md")
    assert "dependency_integration_gate_unavailable" in text
    assert "install the declared producer floor" in text
    assert "no local checker or absence fallback" in text
    assert "check_hard_blocks" not in text


def test_collect_describes_the_scoped_gate_and_blocker_evidence():
    text = _read(SKILLS / "usher" / "collect.md")
    assert (
        "coordination_only and activation-only edges are not integration blockers"
        in text
    )
    assert (
        "gate_point, satisfaction condition/environment and persisted rationale" in text
    )
    assert "a cycle or failed reader halts" in text


def test_collect_consults_the_pin_and_reuses_landed_receipts():
    text = _read(SKILLS / "usher" / "collect.md")
    for required in (
        "workflows item get",
        "workflows version get",
        "merged_at",
        "reviewing-implementation",
        "yoke merge item",
        "never force a jump",
    ):
        assert required in text


def test_dry_run_bypasses_claim_and_reconciliation_writes():
    text = _read(SKILLS / "usher" / "collect.md")
    assert (
        "Dry-run keeps these reads but skips claim acquisition and reconciliation"
        in text
    )
    assert "writes. For execution, acquire every admitted item claim" in text
    plan = _read(SKILLS / "usher" / "plan.md")
    assert "stop without acquiring work claims" in plan
