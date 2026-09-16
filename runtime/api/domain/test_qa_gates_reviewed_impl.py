"""Reviewed-implementation gate coverage for yoke_core.domain.qa_gates.

Sibling to ``test_qa_gates.py`` which holds verification-entry, done, and
epic-simulation coverage. Fixtures are duplicated locally rather than
hoisted to a directory-wide conftest because they are scoped to qa_gates.
"""

from __future__ import annotations

import json
from unittest import mock

from runtime.api.domain.qa_gates_reviewed_impl_test_support import (
    TEST_ITEM_REF,
    add_artifact as _add_artifact,
    add_requirement as _add_requirement,
    add_run as _add_run,
    link_agent_review as _link_agent_review,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.qa_gates import (
    GateTarget,
    LatestCodeRef,
    check_reviewed_implementation_gate,
)

pytest_plugins = ("runtime.api.domain.qa_gates_reviewed_impl_fixture",)

_CAPTURED_SHA = "b" * 40
_DURABLE_HANDLE = {
    "backend": "s3",
    "bucket": "test-artifacts",
    "key": "tenants/1/qa-artifacts/testproj/42/screenshot.png",
}


def _stamped_result(sha: str, branch: str = "feature-branch") -> str:
    """A capture payload carrying the exact revision it was taken against."""
    return json.dumps({"code_identity": {"branch": branch, "sha": sha}})


class TestCheckReviewedImplementationGate:
    def test_tc_empty_requirement_set_refuses(self, qa_db):
        result = check_reviewed_implementation_gate(GateTarget(item_id=42), qa_db)
        assert not result.passed
        assert any("GATE_QA_REQUIREMENTS_EMPTY" in e for e in result.errors)

    def test_tc_passes_when_all_satisfied(self, qa_db):
        req_id = _add_requirement(qa_db)
        _add_run(qa_db, req_id, "pass")
        target = GateTarget(item_id=42)
        result = check_reviewed_implementation_gate(target, qa_db)
        assert result.passed

    def test_tc_fails_when_unsatisfied(self, qa_db):
        _add_requirement(qa_db)
        target = GateTarget(item_id=42)
        result = check_reviewed_implementation_gate(target, qa_db)
        assert not result.passed
        assert any("unsatisfied" in e for e in result.errors)

    def test_tc_unsatisfied_remediation_points_to_advance(self, qa_db):
        """generic gate failures tell the operator which advance command to run."""
        _add_requirement(qa_db)
        target = GateTarget(item_id=42)
        result = check_reviewed_implementation_gate(target, qa_db)
        assert not result.passed
        joined = "\n".join(result.errors)
        assert f"/yoke advance {TEST_ITEM_REF} reviewed-implementation" in joined
        assert "browser QA and project E2E phases automatically" in joined

    def test_tc_passes_when_waived(self, qa_db):
        conn = connect_test_db(qa_db)
        conn.execute(
            "INSERT INTO qa_requirements (item_id, qa_kind, qa_phase, blocking_mode, waived_at) "
            "VALUES (42, 'implementation_review', 'verification', 'blocking', '2024-01-01T00:00:00Z')"
        )
        conn.commit()
        conn.close()
        target = GateTarget(item_id=42)
        result = check_reviewed_implementation_gate(target, qa_db)
        assert result.passed

    def test_tc_browser_evidence_enforcement(self, qa_db):
        """Browser requirements need substrate execution + artifacts."""
        req_id = _add_requirement(
            qa_db,
            qa_kind="plan_case",
            method_id="browser-check",
        )
        # Only agent-executed run — should fail
        _add_run(qa_db, req_id, "pass", performed_by="agent")
        target = GateTarget(item_id=42)
        result = check_reviewed_implementation_gate(target, qa_db)
        assert not result.passed
        assert any("substrate evidence" in e for e in result.errors)

    def test_tc_unstamped_capture_without_checkout_refuses_by_name(self, qa_db):
        """A capture naming no revision can only be judged from a checkout."""
        req_id = _add_requirement(
            qa_db,
            qa_kind="plan_case",
            method_id="browser-check",
        )
        run_id = _add_run(qa_db, req_id, "pass", performed_by="browser_substrate")
        _add_artifact(qa_db, run_id, handle=_DURABLE_HANDLE)
        with mock.patch(
            "yoke_core.domain.qa_gates._resolve_repo_root",
            return_value=None,
        ):
            result = check_reviewed_implementation_gate(GateTarget(item_id=42), qa_db)
        assert not result.passed
        joined = "\n".join(result.errors)
        assert "GATE_QA_BROWSER_PROOF_NEEDS_CHECKOUT" in joined
        assert f"Requirement #{req_id}" in joined
        assert "no exact revision" in joined

    def test_tc_durable_stamped_proof_passes_without_a_checkout(self, qa_db):
        """Durable evidence plus an exact revision needs no customer checkout."""
        req_id = _add_requirement(
            qa_db,
            qa_kind="plan_case",
            method_id="browser-check",
        )
        run_id = _add_run(
            qa_db,
            req_id,
            "pass",
            performed_by="browser_substrate",
            raw_result=_stamped_result(_CAPTURED_SHA),
        )
        _add_artifact(qa_db, run_id, handle=_DURABLE_HANDLE)
        with mock.patch(
            "yoke_core.domain.qa_gates._resolve_repo_root",
            return_value=None,
        ):
            result = check_reviewed_implementation_gate(GateTarget(item_id=42), qa_db)
        assert result.passed, result.errors

    def test_tc_checkout_relative_evidence_without_checkout_refuses(self, qa_db):
        """A path relative to the checkout is unreadable where there is none."""
        req_id = _add_requirement(
            qa_db,
            qa_kind="plan_case",
            method_id="browser-check",
        )
        run_id = _add_run(
            qa_db,
            req_id,
            "pass",
            performed_by="browser_substrate",
            raw_result=_stamped_result(_CAPTURED_SHA),
        )
        _add_artifact(qa_db, run_id, handle="artifacts/screenshot.png")
        with mock.patch(
            "yoke_core.domain.qa_gates._resolve_repo_root",
            return_value=None,
        ):
            result = check_reviewed_implementation_gate(GateTarget(item_id=42), qa_db)
        assert not result.passed
        joined = "\n".join(result.errors)
        assert "GATE_QA_BROWSER_PROOF_NEEDS_CHECKOUT" in joined
        assert "checkout-relative path" in joined

    def test_tc_no_checkout_is_not_applicable_without_browser_methods(self, qa_db):
        req_id = _add_requirement(qa_db)
        _add_run(qa_db, req_id, "pass")
        with mock.patch(
            "yoke_core.domain.qa_gates._resolve_repo_root",
            return_value=None,
        ):
            result = check_reviewed_implementation_gate(GateTarget(item_id=42), qa_db)
        assert result.passed

    def test_tc_browser_evidence_remediation_points_to_advance(self, qa_db):
        """browser evidence failures point back to /yoke advance."""
        req_id = _add_requirement(
            qa_db,
            qa_kind="plan_case",
            method_id="browser-inspection",
        )
        _add_run(qa_db, req_id, "pass", performed_by="agent")
        target = GateTarget(item_id=42)
        result = check_reviewed_implementation_gate(target, qa_db)
        assert not result.passed
        joined = "\n".join(result.errors)
        assert "Re-run each named materialized case" in joined
        assert "yoke qa case run --requirement-id <REQ_ID>" in joined
        assert "yoke qa browser screenshot <URL>" in joined
        assert "without recording a" in joined
        assert "parallel QA verdict" in joined
        assert "yoke qa run add" not in joined
        assert "yoke qa artifact add" not in joined
        assert f"/yoke advance {TEST_ITEM_REF} reviewed-implementation" in joined
        assert "browser QA automatically before updating status" in joined

    def test_tc_browser_evidence_passes_with_substrate(self, qa_db, tmp_path):
        """Browser requirement passes with substrate run + artifact on disk."""
        req_id = _add_requirement(
            qa_db,
            qa_kind="plan_case",
            method_id="browser-check",
        )
        run_id = _add_run(qa_db, req_id, "pass", performed_by="browser_substrate")
        # Create artifact with real file
        art_file = tmp_path / "screenshot.png"
        art_file.write_bytes(b"PNG")
        _add_artifact(qa_db, run_id, str(art_file))
        target = GateTarget(item_id=42)
        result = check_reviewed_implementation_gate(target, qa_db)
        assert result.passed

    def test_tc_browser_inspection_passes_with_linked_agent_verdict(
        self,
        qa_db,
        tmp_path,
    ):
        req_id = _add_requirement(
            qa_db,
            qa_kind="plan_case",
            method_id="browser-inspection",
        )
        capture_run_id = _add_run(
            qa_db,
            req_id,
            None,
            performed_by="browser_substrate",
            execution_status="captured",
            case_outcome="needs_review",
        )
        art_file = tmp_path / "inspection.png"
        art_file.write_bytes(b"PNG")
        _add_artifact(qa_db, capture_run_id, str(art_file))
        review_run_id = _add_run(
            qa_db,
            req_id,
            "pass",
            performed_by="agent",
        )
        _link_agent_review(
            qa_db,
            requirement_id=req_id,
            capture_run_id=capture_run_id,
            review_run_id=review_run_id,
        )

        result = check_reviewed_implementation_gate(
            GateTarget(item_id=42),
            qa_db,
        )

        assert result.passed

    def test_tc_browser_s3_handle_passes_without_local_file(self, qa_db):
        """Uploaded (s3-handle) evidence passes without a machine-local file."""
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
            s3_handle("proj-prod-artifacts", "qa-artifacts/testproj/42/7/shot.png"),
        )
        target = GateTarget(item_id=42)
        result = check_reviewed_implementation_gate(target, qa_db)
        assert result.passed

    def test_tc_non_blocking_ignored(self, qa_db):
        """Non-blocking requirements don't block the gate."""
        _add_requirement(qa_db, blocking="non_blocking")
        target = GateTarget(item_id=42)
        result = check_reviewed_implementation_gate(target, qa_db)
        assert result.passed

    def test_tc_bypass_flag(self, qa_db, monkeypatch):
        monkeypatch.setenv("YOKE_QA_GATE_BYPASS", "1")
        _add_requirement(qa_db)
        target = GateTarget(item_id=42)
        result = check_reviewed_implementation_gate(target, qa_db)
        assert result.passed

    def test_tc_browser_freshness_accepts_exact_sha_match(self, qa_db, tmp_path):
        """Fresh browser runs can match the latest code by explicit SHA."""
        req_id = _add_requirement(
            qa_db,
            qa_kind="plan_case",
            method_id="browser-check",
        )
        run_id = _add_run(
            qa_db,
            req_id,
            "pass",
            performed_by="browser_substrate",
            created_at="2024-01-01T00:00:00Z",
            raw_result=f'{{"code_identity":{{"branch":"{TEST_ITEM_REF}","sha":"fresh123"}}}}',
        )
        art_file = tmp_path / "screenshot.png"
        art_file.write_bytes(b"PNG")
        _add_artifact(qa_db, run_id, str(art_file))
        target = GateTarget(item_id=42)
        with mock.patch(
            "yoke_core.domain.qa_gates._resolve_latest_code_ref",
            return_value=LatestCodeRef(
                branch=TEST_ITEM_REF,
                sha="fresh123",
                timestamp="2025-01-01T00:00:00Z",
            ),
        ):
            result = check_reviewed_implementation_gate(target, qa_db)
        assert result.passed
