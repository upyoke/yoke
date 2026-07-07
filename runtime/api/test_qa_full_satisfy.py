"""satisfy-screenshot-evidence — bridge inspected captures into ac_verification.

Covers ``cmd_satisfy_screenshot_evidence``: matching ac_verification
requirements against an inspected ``browser_smoke``/``browser_diff`` capture,
the no-inspection guard (exit 3), waiver skipping, and the "already satisfied"
no-double-create behaviour.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import qa
from runtime.api.qa_full_test_helpers import make_qa_db_file


@pytest.fixture()
def db_path(tmp_path):
    with make_qa_db_file(tmp_path) as path:
        yield path


class TestSatisfyScreenshotEvidence:
    """cmd_satisfy_screenshot_evidence: batch satisfaction."""

    @staticmethod
    def _seed_inspected_capture(db_path: str, item_id: int) -> int:
        """seed an inspection-verified browser capture.

        satisfy-screenshot-evidence now requires at least one capture with
        execution_status='captured' AND verdict='pass' on a browser_smoke
        or browser_diff run before bridging into ac_verification.
        """
        smoke_req = qa.cmd_requirement_add(
            db_path=db_path, item_id=item_id, qa_kind="browser_smoke",
            qa_phase="verification",
            success_policy='{"steps":[{"action":"navigate","route":"/"},'
                            '{"action":"screenshot","capture":true}]}',
        )
        run_id = qa.cmd_run_add(
            db_path=db_path, requirement_id=smoke_req,
            executor_type="browser_substrate", qa_kind="browser_smoke",
        )
        qa.cmd_run_complete(
            db_path=db_path, run_id=run_id,
            verdict="pass", execution_status="captured",
        )
        return smoke_req

    def test_satisfy_matching_requirements(self, db_path, capsys):
        self._seed_inspected_capture(db_path, 100)
        # Create ac_verification requirement with screenshot evidence
        policy = json.dumps({"requires_screenshot_evidence": True})
        qa.cmd_requirement_add(
            db_path=db_path, item_id=100, qa_kind="ac_verification",
            qa_phase="verification", success_policy=policy,
        )
        capsys.readouterr()
        count = qa.cmd_satisfy_screenshot_evidence(db_path=db_path, item_id=100)
        assert count >= 1

    def test_no_matching_requirements(self, db_path, capsys):
        # guard fires when no inspected capture exists → exit 3.
        qa.cmd_requirement_add(
            db_path=db_path, item_id=100, qa_kind="smoke",
            qa_phase="verification",
        )
        capsys.readouterr()
        with pytest.raises(SystemExit) as exc:
            qa.cmd_satisfy_screenshot_evidence(db_path=db_path, item_id=100)
        assert exc.value.code == 3

    def test_already_satisfied_not_doubled(self, db_path, capsys):
        self._seed_inspected_capture(db_path, 100)
        policy = json.dumps({"requires_screenshot_evidence": True})
        qa.cmd_requirement_add(
            db_path=db_path, item_id=100, qa_kind="ac_verification",
            qa_phase="verification", success_policy=policy,
        )
        capsys.readouterr()
        qa.cmd_satisfy_screenshot_evidence(db_path=db_path, item_id=100)
        capsys.readouterr()
        # Second call should not create additional runs
        count = qa.cmd_satisfy_screenshot_evidence(db_path=db_path, item_id=100)
        assert count == 0

    def test_waived_requirement_skipped(self, db_path, capsys):
        self._seed_inspected_capture(db_path, 100)
        policy = json.dumps({"requires_screenshot_evidence": True})
        req_id = qa.cmd_requirement_add(
            db_path=db_path, item_id=100, qa_kind="ac_verification",
            qa_phase="verification", success_policy=policy,
            blocking_mode="non_blocking",
        )
        qa.cmd_requirement_waive(req_id, "not needed", db_path=db_path)
        capsys.readouterr()
        count = qa.cmd_satisfy_screenshot_evidence(db_path=db_path, item_id=100)
        assert count == 0

    def test_guard_exit3_without_inspection(self, db_path, capsys):
        """capture without inspection (verdict=NULL) → guard blocks."""
        smoke_req = qa.cmd_requirement_add(
            db_path=db_path, item_id=200, qa_kind="browser_smoke",
            qa_phase="verification",
            success_policy='{"steps":[{"action":"navigate","route":"/"},'
                            '{"action":"screenshot","capture":true}]}',
        )
        run_id = qa.cmd_run_add(
            db_path=db_path, requirement_id=smoke_req,
            executor_type="browser_substrate", qa_kind="browser_smoke",
        )
        qa.cmd_run_complete(
            db_path=db_path, run_id=run_id, execution_status="captured",
        )
        policy = json.dumps({"requires_screenshot_evidence": True})
        qa.cmd_requirement_add(
            db_path=db_path, item_id=200, qa_kind="ac_verification",
            qa_phase="verification", success_policy=policy,
        )
        capsys.readouterr()
        with pytest.raises(SystemExit) as exc:
            qa.cmd_satisfy_screenshot_evidence(db_path=db_path, item_id=200)
        assert exc.value.code == 3
