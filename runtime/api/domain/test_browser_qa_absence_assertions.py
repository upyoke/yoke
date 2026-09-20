"""Browser QA — an absence assertion is evidence only if it could fail.

Both outcomes below follow from one rule read off the run rather than off the
author's intent. A case whose assertions never matched an element never saw
the page, so it proved nothing. A case with one assertion that did match has
observed a rendered page, so an absence it also asserts is a real finding and
stays green.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.domain.browser_qa_test_helpers import (
    _run_scenario,
    _seed_item,
    _seed_requirement,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def db_path(tmp_path):
    with init_test_db(tmp_path) as path:
        yield path


#: The absence guard that reads as a settle wait and asserts nothing positive.
_ABSENCE_GUARD = {
    "action": "assert",
    "target": ".review-shot.is-pending",
    "check": "hidden",
}

#: What the runner reports for that guard when the element was on the page
#: and genuinely hidden: a real observation, so no zero-match report.
_MATCHED_THE_ELEMENT = {"success": True, "artifacts": []}

#: What the runner reports for that guard when the page held no such element.
_MATCHED_NOTHING = {
    "success": True,
    "artifacts": [],
    "vacuous_absence": {
        "check": "hidden",
        "target": ".review-shot.is-pending",
        "matched_elements": 0,
    },
}


def _guard_only_case(db_path: str, item_id: int, method_id: str) -> int:
    """Seed a case whose only assertion is the absence guard."""
    _seed_item(db_path, item_id)
    return _seed_requirement(
        db_path, item_id, method_id,
        {"steps": [{"action": "navigate", "route": "/inbox"}, _ABSENCE_GUARD]},
    )


class TestAssertionThatMatchedNothing:
    def test_guard_only_case_matching_nothing_cannot_pass(
        self, db_path: str,
    ) -> None:
        """An absence guard with no positive counterpart proved nothing."""
        req_id = _guard_only_case(db_path, 310, "browser-check")

        result = _run_scenario(
            db_path, 310, requirement_id=req_id,
            assertion_responses={".review-shot.is-pending": _MATCHED_NOTHING},
        )

        run = result.runs[0]
        assert run.verdict == "fail"
        assert run.execution_status == "capture_failed"
        assert "assertion_vacuous_absence" in run.errors
        assert ".review-shot.is-pending" in run.errors
        assert run.vacuous_absences[0]["matched_elements"] == 0

    def test_failure_names_a_recovery_for_the_case_that_triggered_it(
        self, db_path: str,
    ) -> None:
        """The author is told how to make this very case prove something."""
        req_id = _guard_only_case(db_path, 311, "browser-check")

        result = _run_scenario(
            db_path, 311, requirement_id=req_id,
            assertion_responses={".review-shot.is-pending": _MATCHED_NOTHING},
        )

        errors = result.runs[0].errors
        assert (
            f"yoke qa requirement update --requirement-id {req_id} "
            "--field method_config --stdin"
        ) in errors
        assert f"yoke qa case run --requirement-id {req_id}" in errors

    def test_same_assertion_against_a_populated_page_passes(
        self, db_path: str,
    ) -> None:
        """The element was there and hidden, so the case observed it."""
        req_id = _guard_only_case(db_path, 312, "browser-check")

        result = _run_scenario(
            db_path, 312, requirement_id=req_id,
            assertion_responses={
                ".review-shot.is-pending": _MATCHED_THE_ELEMENT,
            },
        )

        run = result.runs[0]
        assert run.verdict == "pass"
        assert run.errors == ""
        assert run.vacuous_absences == []

    def test_absence_beside_an_assertion_that_matched_stays_a_pass(
        self, db_path: str,
    ) -> None:
        """A control genuinely gone at this width is a real finding.

        The case also asserts something the page does show, so the screen it
        read the absence off is known to have rendered.
        """
        _seed_item(db_path, 313)
        req_id = _seed_requirement(
            db_path, 313, "browser-check",
            {"steps": [
                {"action": "navigate", "route": "/inbox"},
                {"action": "assert", "target": "nav", "check": "visible"},
                {"action": "assert", "target": ".nav-hamburger",
                 "check": "hidden"},
            ]},
        )

        result = _run_scenario(
            db_path, 313, requirement_id=req_id,
            assertion_responses={
                ".nav-hamburger": {
                    "success": True,
                    "artifacts": [],
                    "vacuous_absence": {
                        "check": "hidden",
                        "target": ".nav-hamburger",
                        "matched_elements": 0,
                    },
                },
            },
        )

        run = result.runs[0]
        assert run.verdict == "pass"
        # Still recorded: a reader of the run sees which guard proved nothing
        # even where the case as a whole observed the page.
        assert run.vacuous_absences[0]["target"] == ".nav-hamburger"

    def test_capture_metadata_carries_the_guard_that_matched_nothing(
        self, tmp_path: Path, db_path: str,
    ) -> None:
        """A reviewer judging the bundle reads it off the capture itself."""
        _seed_item(db_path, 314)
        req_id = _seed_requirement(
            db_path, 314, "browser-inspection",
            {"steps": [
                {"action": "navigate", "route": "/inbox"},
                _ABSENCE_GUARD,
                {"action": "screenshot", "capture": True},
            ]},
        )
        shot_file = tmp_path / "inbox.png"
        shot_file.write_bytes(b"PNG")

        _run_scenario(
            db_path, 314, requirement_id=req_id,
            assertion_responses={".review-shot.is-pending": _MATCHED_NOTHING},
            execute_step_responses=[
                {"success": True, "artifacts": []},
                {"success": True, "artifacts": [str(shot_file)]},
            ],
        )

        conn = connect_test_db(db_path)
        metadata = conn.execute(
            "SELECT metadata FROM qa_artifacts ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        conn.close()
        recorded = json.loads(metadata)["vacuous_absences"]
        assert recorded[0]["target"] == ".review-shot.is-pending"
        assert recorded[0]["matched_elements"] == 0
