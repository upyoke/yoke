"""Usher admission consumes the producer's scoped integration decision."""

from runtime.api.skill_doc_regressions_test_helpers import SKILLS, _read


def test_collect_reads_the_registered_integration_gate():
    text = _read(SKILLS / "usher" / "collect.md")
    assert "yoke items dependency list PREFIX-N --json" in text
    assert "integration_gate.is_blocked" in text
    assert "Order blockers first" in text


def test_collect_refuses_missing_gate_without_an_unscoped_fallback():
    text = _read(SKILLS / "usher" / "collect.md")
    assert "an absent gate (no local fallback)" in text
    assert "check_hard_blocks" not in text


def test_collect_never_relands_a_merged_item():
    text = _read(SKILLS / "usher" / "collect.md")
    assert "yoke items get PREFIX-N merged_at" in text
    assert "Never land an item with `merged_at` again" in text


def test_dry_run_bypasses_claim_and_reconciliation_writes():
    text = _read(SKILLS / "usher" / "collect.md")
    assert "Dry run claims nothing." in text
    assert "yoke claims work acquire --item PREFIX-N --reason usher_collect" in text
    plan = _read(SKILLS / "usher" / "plan.md")
    assert "write nothing and claim nothing" in plan
