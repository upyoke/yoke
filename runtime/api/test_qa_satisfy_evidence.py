"""``qa.cmd_satisfy_screenshot_evidence`` and visible-defect failure recording —
the bridge from inspected browser_smoke captures into ac_verification, plus
the gate's behaviour when the underlying screenshot evaluation fails."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import qa
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.qa_test_helpers import make_qa_db_file


@pytest.fixture()
def db_path(tmp_path: Path):
    with make_qa_db_file(tmp_path) as path:
        yield path


class TestSatisfyScreenshotEvidence:
    @staticmethod
    def _seed_inspected_capture(db_path: str, item_id: int) -> int:
        """Seed a browser_smoke requirement + inspected capture qa_run.

        satisfy-screenshot-evidence now requires at least one
        capture row with execution_status='captured' AND verdict='pass'
        (i.e., inspection has already confirmed quality) before bridging
        into ac_verification. This helper gets a fixture into that state.
        """
        smoke_req = qa.cmd_requirement_add(
            db_path=db_path,
            item_id=item_id,
            qa_kind="browser_smoke",
            qa_phase="verification",
            success_policy='{"steps":[{"action":"navigate","route":"/"},'
                            '{"action":"screenshot","capture":true}]}',
        )
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=smoke_req,
            executor_type="browser_substrate",
            qa_kind="browser_smoke",
        )
        qa.cmd_run_complete(
            db_path=db_path,
            run_id=run_id,
            verdict="pass",
            execution_status="captured",
        )
        return smoke_req

    def test_satisfies_requirements(self, db_path: str) -> None:
        self._seed_inspected_capture(db_path, item_id=50)
        rid = qa.cmd_requirement_add(
            db_path=db_path,
            item_id=50,
            qa_kind="ac_verification",
            qa_phase="verification",
            success_policy='{"requires_screenshot_evidence": true}',
        )
        count = qa.cmd_satisfy_screenshot_evidence(db_path=db_path, item_id=50)
        assert count == 1

        # Verify a passing browser_substrate run was created
        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT verdict, executor_type FROM qa_runs WHERE qa_requirement_id = %s",
            (rid,),
        ).fetchone()
        conn.close()
        assert row[0] == "pass"
        assert row[1] == "browser_substrate"

    def test_idempotent(self, db_path: str) -> None:
        self._seed_inspected_capture(db_path, item_id=50)
        qa.cmd_requirement_add(
            db_path=db_path, item_id=50, qa_kind="ac_verification",
            qa_phase="verification",
            success_policy='{"requires_screenshot_evidence": true}',
        )
        count1 = qa.cmd_satisfy_screenshot_evidence(db_path=db_path, item_id=50)
        assert count1 == 1
        count2 = qa.cmd_satisfy_screenshot_evidence(db_path=db_path, item_id=50)
        # Already satisfied, so no unsatisfied reqs found — returns 0 (matches shell)
        assert count2 == 0

    def test_no_matching_requirements(self, db_path: str) -> None:
        # Guard fires before the "no requirements" path when no capture exists
        # for the item. Exit 3 signals missing inspection evidence.
        with pytest.raises(SystemExit) as exc:
            qa.cmd_satisfy_screenshot_evidence(db_path=db_path, item_id=999)
        assert exc.value.code == 3

    def test_skips_waived_requirements(self, db_path: str) -> None:
        self._seed_inspected_capture(db_path, item_id=60)
        rid = qa.cmd_requirement_add(
            db_path=db_path, item_id=60, qa_kind="ac_verification",
            qa_phase="verification", blocking_mode="non_blocking",
            success_policy='{"requires_screenshot_evidence": true}',
        )
        qa.cmd_requirement_waive(rid, "not needed", db_path=db_path)
        count = qa.cmd_satisfy_screenshot_evidence(db_path=db_path, item_id=60)
        assert count == 0

    def test_refuses_without_inspected_capture(self, db_path: str) -> None:
        """Guard: no browser_smoke verdict='pass' exists → exit 3."""
        qa.cmd_requirement_add(
            db_path=db_path, item_id=70, qa_kind="ac_verification",
            qa_phase="verification",
            success_policy='{"requires_screenshot_evidence": true}',
        )
        # Seed only a capture-only row (verdict=NULL), not an inspection pass.
        smoke_req = qa.cmd_requirement_add(
            db_path=db_path, item_id=70, qa_kind="browser_smoke",
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
        )  # no verdict → still awaiting inspection
        with pytest.raises(SystemExit) as exc:
            qa.cmd_satisfy_screenshot_evidence(db_path=db_path, item_id=70)
        assert exc.value.code == 3


class TestVisibleDefectFailureRecording:
    """browser_smoke failing run with defect-specific raw_result.

    Models the AC-consistent-but-visibly-broken scenario: a page satisfies
    its acceptance criteria but has a rendering anomaly (e.g., raw Unicode
    escapes). The screenshot evaluation gate should record a failing run
    with the specific defect, and satisfy-screenshot-evidence must NOT be
    called (the ac_verification requirement stays unsatisfied).
    """

    def test_defect_specific_fail_stored(self, db_path: str) -> None:
        """Failing browser_smoke run stores defect-specific raw_result."""
        smoke_rid = qa.cmd_requirement_add(
            db_path=db_path,
            item_id=70,
            qa_kind="browser_smoke",
            qa_phase="verification",
            success_policy='{"steps": [{"action": "navigate", "route": "/"}, {"action": "screenshot", "capture": true}]}',
        )
        defect_msg = (
            "Screenshot evaluation: visible defect detected — "
            "raw Unicode escape sequences \\u2728 rendered as literal text in hero section"
        )
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=smoke_rid,
            executor_type="browser_substrate",
            qa_kind="browser_smoke",
            verdict="fail",
            raw_result=defect_msg,
        )
        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT verdict, raw_result FROM qa_runs WHERE id = %s",
            (run_id,),
        ).fetchone()
        conn.close()
        assert row[0] == "fail"
        assert "visible defect detected" in row[1]
        assert "\\u2728" in row[1]

    def test_screenshot_evidence_unsatisfied_after_defect_fail(self, db_path: str) -> None:
        """satisfy-screenshot-evidence leaves ac_verification unsatisfied when
        the browser_smoke gate recorded a visible-defect failure.

        This models the visible-defect-check contract: when Check 1 (visible defect)
        fails, the gate blocks before calling satisfy-screenshot-evidence.
        The ac_verification requirement with requires_screenshot_evidence
        must remain unsatisfied.
        """
        # Seed both requirement types for the same item
        _smoke_rid = qa.cmd_requirement_add(
            db_path=db_path,
            item_id=71,
            qa_kind="browser_smoke",
            qa_phase="verification",
            success_policy='{"steps": [{"action": "navigate", "route": "/"}, {"action": "screenshot", "capture": true}]}',
        )
        qa.cmd_requirement_add(
            db_path=db_path,
            item_id=71,
            qa_kind="ac_verification",
            qa_phase="verification",
            success_policy='{"requires_screenshot_evidence": true}',
        )

        # Record a visible-defect failure on browser_smoke
        qa.cmd_run_add(
            db_path=db_path,
            requirement_id=_smoke_rid,
            executor_type="browser_substrate",
            qa_kind="browser_smoke",
            verdict="fail",
            raw_result="Screenshot evaluation: visible defect detected — layout collapse in main container",
        )

        # The gate blocks here — satisfy-screenshot-evidence is NOT called.
        # Verify the ac_verification requirement has no passing run.
        conn = connect_test_db(db_path)
        unsatisfied = conn.execute(
            """SELECT COUNT(*) FROM qa_requirements r
               WHERE r.item_id = 71
                 AND r.qa_kind = 'ac_verification'
                 AND r.success_policy LIKE '%requires_screenshot_evidence%'
                 AND r.id NOT IN (
                   SELECT qa_requirement_id FROM qa_runs
                   WHERE verdict = 'pass' AND executor_type = 'browser_substrate'
                 )""",
        ).fetchone()[0]
        conn.close()
        assert unsatisfied == 1, "ac_verification requirement should remain unsatisfied after visible-defect failure"
