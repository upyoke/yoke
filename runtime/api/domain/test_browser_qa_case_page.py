"""A Browser case owns the page it runs on, and says what it observed there.

Before this, every step landed on whichever page the daemon happened to be
holding, and a step's stated viewport stayed applied afterwards. One case
therefore inherited the page of the case before it — its route and its phone
width — partway through, and the resulting timeouts read as product defects.
These cover the page a case opens for itself, the width it opens at, and the
page state that travels with each capture.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from yoke_contracts.browser_qa_contract import DEFAULT_BROWSER_VIEWPORT
from yoke_core.domain import browser_qa
from runtime.api.domain.browser_qa_test_helpers import (
    FAKE_PAGE_ID,
    _browser_check_steps,
    _run_scenario,
    _seed_item,
    _seed_requirement,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def db_path(tmp_path):
    with init_test_db(tmp_path) as path:
        yield path


def _artifact_metadata(db_path: str) -> list[dict]:
    conn = connect_test_db(db_path)
    try:
        rows = conn.execute(
            "SELECT metadata FROM qa_artifacts ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [json.loads(row[0]) for row in rows]


class TestCaseOwnsItsPage:
    def test_case_opens_and_closes_its_own_page(self, db_path: str) -> None:
        _seed_item(db_path, 700)
        _seed_requirement(
            db_path, 700, "browser-check",
            {"base_url": "http://localhost:9999", "steps": _browser_check_steps()},
        )
        opened: list[dict] = []
        closed: list[str] = []

        result = _run_scenario(
            db_path, 700,
            execute_step_responses=[{"success": True, "artifacts": []}],
            opened_pages=opened,
            closed_pages=closed,
        )

        assert result.verdict == "pass"
        assert opened == [dict(DEFAULT_BROWSER_VIEWPORT)]
        assert closed == [FAKE_PAGE_ID]

    def test_case_opens_at_the_viewport_it_declares(self, db_path: str) -> None:
        _seed_item(db_path, 701)
        _seed_requirement(
            db_path, 701, "browser-check",
            {
                "base_url": "http://localhost:9999",
                "viewport": {"width": 375, "height": 812},
                "steps": _browser_check_steps(),
            },
        )
        opened: list[dict] = []

        _run_scenario(
            db_path, 701,
            execute_step_responses=[{"success": True, "artifacts": []}],
            opened_pages=opened,
        )

        assert opened == [{"width": 375, "height": 812}]

    def test_every_step_addresses_the_case_page(self, db_path: str) -> None:
        _seed_item(db_path, 702)
        _seed_requirement(
            db_path, 702, "browser-check",
            {"base_url": "http://localhost:9999", "steps": _browser_check_steps()},
        )
        addressed: list[str] = []

        def _record_step(step, base_url, artifact_dir, page_id):
            addressed.append(page_id)
            return {"success": True, "artifacts": []}

        with mock.patch.object(
            browser_qa, "_execute_step", side_effect=_record_step
        ):
            _run_scenario(db_path, 702, execute_step_responses=None)

        assert addressed == [FAKE_PAGE_ID, FAKE_PAGE_ID]

    def test_a_case_that_cannot_open_a_page_refuses_by_name(
        self, db_path: str
    ) -> None:
        _seed_item(db_path, 703)
        _seed_requirement(
            db_path, 703, "browser-check",
            {"base_url": "http://localhost:9999", "steps": _browser_check_steps()},
        )

        result = _run_scenario(
            db_path, 703,
            execute_step_responses=[{"success": True, "artifacts": []}],
            open_page_error="daemon opened no page",
        )

        assert result.verdict == "fail"
        assert "page_open_failure" in result.runs[0].errors
        assert "daemon opened no page" in result.runs[0].errors

    def test_an_unusable_declared_viewport_is_refused(self, db_path: str) -> None:
        _seed_item(db_path, 704)
        _seed_requirement(
            db_path, 704, "browser-check",
            {
                "base_url": "http://localhost:9999",
                "viewport": {"width": 0, "height": 812},
                "steps": _browser_check_steps(),
            },
        )

        result = _run_scenario(
            db_path, 704,
            execute_step_responses=[{"success": True, "artifacts": []}],
        )

        assert result.runs[0].verdict == "error"
        assert "case_viewport_invalid" in result.runs[0].errors


class TestCaptureRecordsWhatWasObserved:
    def test_capture_carries_the_observed_viewport_and_url(
        self, tmp_path: Path, db_path: str
    ) -> None:
        _seed_item(db_path, 705)
        _seed_requirement(
            db_path, 705, "browser-inspection",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "navigate", "route": "/#/shipping"},
                    {"action": "screenshot", "capture": True, "label": "shipping"},
                ],
            },
        )
        shot = tmp_path / "shipping.png"
        shot.write_bytes(b"PNG")

        _run_scenario(
            db_path, 705,
            execute_step_responses=[
                {
                    "success": True,
                    "artifacts": [],
                    "viewport": {"width": 1440, "height": 900},
                    "url": "http://localhost:9999/#/shipping",
                },
                {
                    "success": True,
                    "artifacts": [str(shot)],
                    "viewport": {"width": 1440, "height": 900},
                    "url": "http://localhost:9999/#/shipping?project=yoke",
                },
            ],
        )

        recorded = _artifact_metadata(db_path)
        assert len(recorded) == 1
        assert recorded[0]["viewport"] == {"width": 1440, "height": 900}
        assert (
            recorded[0]["observed_url"]
            == "http://localhost:9999/#/shipping?project=yoke"
        )
        # The route the case navigated to stays beside what was observed, so
        # the two can be compared rather than conflated.
        assert recorded[0]["route"] == "/#/shipping"
