"""Tests for qa_gates.py — verification entry, done, and epic-simulation gates,
plus bypass flags and target parsing."""

from __future__ import annotations

from unittest import mock

from runtime.api.domain.qa_gate_test_support import (
    add_artifact as _add_artifact,
    add_requirement as _add_requirement,
    add_run as _add_run,
    add_simulation as _add_simulation,
    apply_items_only as _apply_items_only,
    qa_db as qa_db,
)
from runtime.api.fixtures.file_test_db import init_test_db
from yoke_core.domain.qa_gates import (
    GateTarget,
    LatestCodeRef,
    check_done_gate,
    check_epic_simulation_gate,
    check_verification_entry,
)

TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


# --- check_verification_entry ---


class TestCheckVerificationEntry:
    def test_tc_passes_when_requirement_exists(self, qa_db):
        _add_requirement(qa_db)
        target = GateTarget.parse("42")
        result = check_verification_entry(target, qa_db)
        assert result.passed

    def test_tc_fails_when_no_requirements(self, qa_db):
        target = GateTarget.parse("42")
        result = check_verification_entry(target, qa_db)
        assert not result.passed
        assert any("no qa_requirements found" in e for e in result.errors)
        assert any(
            "--workflow-transition reviewed-implementation" in error
            for error in result.errors
        )

    def test_epic_task_recovery_names_the_derived_transition(self, qa_db):
        target = GateTarget.parse("833:5")
        with mock.patch(
            "yoke_core.domain.qa_gates.item_transition_for_gate",
            return_value="qa-review",
        ):
            result = check_verification_entry(target, qa_db)

        assert not result.passed
        assert any(
            "python3 -m yoke_core.domain.qa requirement-add" in error
            and "--workflow-transition qa-review" in error
            for error in result.errors
        )

    def test_tc_bypass_flag(self, qa_db, monkeypatch):
        monkeypatch.setenv("YOKE_QA_GATE_BYPASS", "1")
        target = GateTarget.parse("42")
        result = check_verification_entry(target, qa_db)
        assert result.passed

    def test_tc_graceful_without_qa_tables(self, tmp_path):
        # Gate passes gracefully if the qa_requirements table doesn't exist.
        with init_test_db(tmp_path, apply_schema=_apply_items_only) as db_path:
            target = GateTarget.parse("42")
            result = check_verification_entry(target, db_path)
            assert result.passed


# Reviewed-implementation gate coverage lives in test_qa_gates_reviewed_impl.py.
# --- check_done_gate ---


class TestCheckDoneGate:
    def test_tc_passes_when_all_satisfied(self, qa_db):
        req_id = _add_requirement(qa_db, qa_phase="verification")
        _add_run(qa_db, req_id, "pass")
        req_id2 = _add_requirement(qa_db, qa_phase="post_deploy")
        _add_run(qa_db, req_id2, "pass")
        target = GateTarget.parse("42")
        result = check_done_gate(target, qa_db)
        assert result.passed

    def test_tc_fails_when_unsatisfied_any_phase(self, qa_db):
        _add_requirement(qa_db, qa_phase="post_deploy")
        target = GateTarget.parse("42")
        result = check_done_gate(target, qa_db)
        assert not result.passed
        assert any("done" in e for e in result.errors)

    def test_tc_bypass_flag(self, qa_db, monkeypatch):
        monkeypatch.setenv("YOKE_QA_GATE_BYPASS", "1")
        _add_requirement(qa_db)
        target = GateTarget.parse("42")
        result = check_done_gate(target, qa_db)
        assert result.passed

    def test_tc_browser_s3_handle_passes_without_local_file(self, qa_db):
        # Done gate accepts uploaded evidence structurally: an s3 handle is
        # durable-by-construction and needs no file on this machine.
        from yoke_core.domain.qa_artifact_handle import s3_handle

        req_id = _add_requirement(
            qa_db,
            qa_kind="plan_case",
            method_id="browser-check",
        )
        run_id = _add_run(qa_db, req_id, "pass", performed_by="browser_substrate")
        _add_artifact(
            qa_db,
            run_id,
            s3_handle("proj-prod-artifacts", "qa-artifacts/testproj/42/8/shot.png"),
        )
        target = GateTarget.parse("42")
        result = check_done_gate(target, qa_db)
        assert result.passed

    def test_tc_browser_sha_mismatch_blocks_done(self, qa_db, tmp_path):
        # Done gate rejects browser passes recorded against older code.
        req_id = _add_requirement(
            qa_db,
            qa_kind="plan_case",
            method_id="browser-check",
        )
        raw = f'{{"code_identity":{{"branch":"{TEST_ITEM_REF}","sha":"old123"}}}}'
        run_id = _add_run(
            qa_db,
            req_id,
            "pass",
            performed_by="browser_substrate",
            created_at="2024-01-01T00:00:00Z",
            raw_result=raw,
        )
        art_file = tmp_path / "done-shot.png"
        art_file.write_bytes(b"PNG")
        _add_artifact(qa_db, run_id, str(art_file))
        target = GateTarget.parse("42")
        latest = LatestCodeRef(
            branch=TEST_ITEM_REF,
            sha="fresh999",
            timestamp="2025-01-01T00:00:00Z",
        )
        with mock.patch(
            "yoke_core.domain.qa_gates._resolve_latest_code_ref",
            return_value=latest,
        ):
            result = check_done_gate(target, qa_db)
        assert not result.passed
        assert any("Latest SHA: fresh999" in e for e in result.errors)


# --- check_epic_simulation_gate ---


class TestCheckEpicSimulationGate:
    def test_tc_clean_passes(self, qa_db):
        _add_simulation(qa_db, 42, "integration", "pass", "")
        result = check_epic_simulation_gate(42, qa_db)
        assert result.passed

    def test_tc_gaps_non_critical_passes(self, qa_db):
        body = "### GAP #1: Minor spacing issue\nSeverity: [WARNING]\nRecommendation: PROCEED"
        _add_simulation(qa_db, 42, "integration", "fail", body)
        result = check_epic_simulation_gate(42, qa_db)
        assert result.passed

    def test_tc_undetermined_never_passes(self, qa_db):
        _add_simulation(
            qa_db, 42, "integration", "undetermined", "", "No final verdict."
        )
        result = check_epic_simulation_gate(42, qa_db)
        assert not result.passed
        assert any("No final verdict" in error for error in result.errors)

    def test_tc_gaps_non_critical_logs_summary(self, qa_db, capsys):
        body = (
            "## Gaps Found: 1 (0 critical, 0 warning, 1 note)\n\n"
            "### GAP #1: Minor documentation drift\nSeverity: [NOTE]\nRecommendation: PROCEED"
        )
        _add_simulation(qa_db, 42, "integration", "fail", body)
        result = check_epic_simulation_gate(42, qa_db)
        captured = capsys.readouterr()
        assert result.passed
        assert "## Gaps Found: 1" in captured.err
        assert "### GAP #1: Minor documentation drift" in captured.err

    def test_tc_gaps_critical_fails(self, qa_db):
        body = "### GAP #1: Data loss\nSeverity: [CRITICAL]\nRecommendation: BLOCK"
        _add_simulation(qa_db, 42, "integration", "fail", body)
        result = check_epic_simulation_gate(42, qa_db)
        assert not result.passed
        assert any("blocking gaps" in e for e in result.errors)

    def test_tc_no_simulation_fails(self, qa_db):
        result = check_epic_simulation_gate(42, qa_db)
        assert not result.passed
        assert any("No integration simulation" in e for e in result.errors)

    def test_tc_bypass_flag(self, qa_db, monkeypatch):
        monkeypatch.setenv("YOKE_SKIP_SIMULATION", "1")
        result = check_epic_simulation_gate(42, qa_db)
        assert result.passed
