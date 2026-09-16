"""The reviewed-implementation gate on a host with no project checkout.

Sibling to ``test_qa_gates_reviewed_impl.py``. A control plane serving a
customer project holds no checkout of it, and the gate used to refuse every
Browser requirement on that ground alone. These cover what it accepts there
instead — durable evidence stamped with a revision the control plane records
— and the four things it still refuses.
"""

from __future__ import annotations

import json
from unittest import mock

from runtime.api.domain.qa_gates_reviewed_impl_test_support import (
    add_artifact as _add_artifact,
    add_requirement as _add_requirement,
    add_run as _add_run,
    record_lane_revision as _record_lane_revision,
)
from yoke_core.domain.qa_gates import (
    GateTarget,
    check_reviewed_implementation_gate,
)

pytest_plugins = ("runtime.api.domain.qa_gates_reviewed_impl_fixture",)

_CAPTURED_SHA = "b" * 40
_SUPERSEDED_SHA = "e" * 40
_DURABLE_HANDLE = {
    "backend": "s3",
    "bucket": "test-artifacts",
    "key": "tenants/1/qa-artifacts/testproj/42/screenshot.png",
}


def _stamped_result(sha: str, branch: str = "feature-branch") -> str:
    """A capture payload carrying the exact revision it was taken against."""
    return json.dumps({"code_identity": {"branch": branch, "sha": sha}})


class TestReviewedImplementationGateWithoutCheckout:
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
        _record_lane_revision(qa_db, _CAPTURED_SHA)
        with mock.patch(
            "yoke_core.domain.qa_gates._resolve_repo_root",
            return_value=None,
        ):
            result = check_reviewed_implementation_gate(GateTarget(item_id=42), qa_db)
        assert result.passed, result.errors
    def test_tc_stale_full_sha_capture_without_checkout_refuses(self, qa_db):
        """A full-length SHA is identity, not freshness.

        Without a checkout there is no branch to read, so the comparison runs
        against the revisions the control plane records for the item. A
        capture of some other commit is stale there exactly as it would be
        against a branch head.
        """
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
            raw_result=_stamped_result(_SUPERSEDED_SHA),
        )
        _add_artifact(qa_db, run_id, handle=_DURABLE_HANDLE)
        _record_lane_revision(qa_db, _CAPTURED_SHA)
        with mock.patch(
            "yoke_core.domain.qa_gates._resolve_repo_root",
            return_value=None,
        ):
            result = check_reviewed_implementation_gate(GateTarget(item_id=42), qa_db)
        assert not result.passed
        joined = "\n".join(result.errors)
        assert "stale passing runs" in joined
        assert _CAPTURED_SHA in joined
        assert _SUPERSEDED_SHA in joined
    def test_tc_item_with_no_recorded_revision_refuses(self, qa_db):
        """Nothing recorded to compare against is unverifiable, not fresh."""
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
        assert not result.passed
        joined = "\n".join(result.errors)
        assert "GATE_QA_BROWSER_PROOF_NEEDS_CHECKOUT" in joined
        assert "records no revision for the item" in joined
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
        _record_lane_revision(qa_db, _CAPTURED_SHA)
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

    def test_a_capture_cannot_be_the_revision_it_is_judged_against(self, qa_db):
        """A run's own recorded revision is withheld from the comparison.

        The revision set is drawn from what recorded the item's delivery. One
        of its sources reaches back into the blocking runs themselves once a
        queue landing is recorded, and a freshness check fed that source would
        measure every capture against its own SHA. Here the only revision the
        item records is the lane head, and a capture of some other commit is
        refused rather than accepted on its own authority.
        """
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
            raw_result=_stamped_result(_SUPERSEDED_SHA),
        )
        _add_artifact(qa_db, run_id, handle=_DURABLE_HANDLE)
        _record_lane_revision(qa_db, _CAPTURED_SHA)
        from yoke_core.domain.qa_browser_checkout_free_proof import (
            recorded_item_revisions,
        )
        from runtime.api.fixtures.file_test_db import connect_test_db

        conn = connect_test_db(qa_db)
        try:
            revisions = recorded_item_revisions(conn, 42)
        finally:
            conn.close()
        assert _SUPERSEDED_SHA not in revisions
        assert _CAPTURED_SHA in revisions
