"""Browser QA — screenshot classification, hard-blocking, and data-envelope unwrap."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import browser_qa
from yoke_core.domain.browser_qa_test_helpers import (
    _patch_external_deps,
    _run_scenario,
    _seed_item,
    _seed_requirement,
)
from runtime.api.fixtures.file_test_db import init_test_db


@pytest.fixture
def db_path(tmp_path):
    with init_test_db(tmp_path) as path:
        yield path


# ---------------------------------------------------------------------------
# Screenshot step classification
# ---------------------------------------------------------------------------

class TestIsScreenshotStep:
    """_is_screenshot_step classification."""

    def test_screenshot_action_requires_capture(self) -> None:
        assert (
            browser_qa._is_screenshot_step({"action": "screenshot", "capture": True})
            is True
        )

    def test_navigate_action_not_screenshot(self) -> None:
        assert browser_qa._is_screenshot_step({"action": "navigate"}) is False

    def test_screenshot_action_without_capture_not_screenshot(self) -> None:
        assert browser_qa._is_screenshot_step({"action": "screenshot"}) is False

    def test_non_screenshot_action_with_capture_not_screenshot(self) -> None:
        assert browser_qa._is_screenshot_step({"action": "click", "capture": True}) is False

    def test_non_dict_returns_false(self) -> None:
        assert browser_qa._is_screenshot_step("screenshot") is False

    def test_empty_dict_returns_false(self) -> None:
        assert browser_qa._is_screenshot_step({}) is False


# ---------------------------------------------------------------------------
# Screenshot storage failure must hard-block
# ---------------------------------------------------------------------------

class TestScreenshotStorageHardBlock:
    """screenshot steps must fail on missing/nonexistent artifacts."""

    def test_ac1_no_artifact_path_fails_run(self, db_path: str) -> None:
        """AC-1: screenshot step with no artifact path returned fails the run."""
        _seed_item(db_path, 600)
        _seed_requirement(
            db_path, 600, "browser_smoke",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    {"action": "screenshot", "capture": True, "label": "home"},
                ],
            },
        )

        result = _run_scenario(
            db_path, 600,
            execute_step_responses=[
                {"success": True, "artifacts": []},  # navigate — OK
                {"success": True, "artifacts": []},  # screenshot — no artifact!
            ],
        )

        assert result.verdict == "fail"
        assert result.runs[0].verdict == "fail"
        assert "no_screenshot_artifact" in result.runs[0].errors

    def test_ac2_artifact_not_on_disk_fails_run(self, tmp_path: Path, db_path: str) -> None:
        """AC-2: returned artifact path that doesn't exist on disk fails the run."""
        _seed_item(db_path, 601)
        _seed_requirement(
            db_path, 601, "browser_smoke",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "screenshot", "capture": True, "label": "login"},
                ],
            },
        )

        nonexistent = str(tmp_path / "does_not_exist.png")
        result = _run_scenario(
            db_path, 601,
            execute_step_responses=[
                {"success": True, "artifacts": [nonexistent]},
            ],
        )

        assert result.verdict == "fail"
        assert result.runs[0].verdict == "fail"
        assert "artifact_not_on_disk" in result.runs[0].errors

    def test_ac3_completeness_check_fails_on_mismatch(self, tmp_path: Path, db_path: str) -> None:
        """AC-3: expected>recorded screenshots fails the run even if steps succeeded."""
        _seed_item(db_path, 602)
        _seed_requirement(
            db_path, 602, "browser_smoke",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "screenshot", "capture": True, "label": "page1"},
                    {"action": "screenshot", "capture": True, "label": "page2"},
                ],
            },
        )

        # First screenshot exists, second doesn't
        shot1 = tmp_path / "page1.png"
        shot1.write_bytes(b"PNG")
        nonexistent = str(tmp_path / "missing.png")

        result = _run_scenario(
            db_path, 602,
            execute_step_responses=[
                {"success": True, "artifacts": [str(shot1)]},
                {"success": True, "artifacts": [nonexistent]},
            ],
        )

        assert result.verdict == "fail"
        assert result.runs[0].expected_screenshots == 2
        assert result.runs[0].recorded_screenshots == 1

    def test_ac3_completeness_passes_when_all_recorded(self, tmp_path: Path, db_path: str) -> None:
        """AC-3: when all expected screenshots are recorded, run passes."""
        _seed_item(db_path, 603)
        _seed_requirement(
            db_path, 603, "browser_smoke",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "screenshot", "capture": True, "label": "page1"},
                    {"action": "screenshot", "capture": True, "label": "page2"},
                ],
            },
        )

        shot1 = tmp_path / "page1.png"
        shot1.write_bytes(b"PNG")
        shot2 = tmp_path / "page2.png"
        shot2.write_bytes(b"PNG")

        result = _run_scenario(
            db_path, 603,
            execute_step_responses=[
                {"success": True, "artifacts": [str(shot1)]},
                {"success": True, "artifacts": [str(shot2)]},
            ],
        )

        assert result.verdict == "pass"
        assert result.runs[0].expected_screenshots == 2
        assert result.runs[0].recorded_screenshots == 2

    def test_ac6_non_screenshot_steps_unaffected(self, db_path: str) -> None:
        """AC-6: navigate/click steps without screenshot requirement pass normally."""
        _seed_item(db_path, 604)
        _seed_requirement(
            db_path, 604, "browser_smoke",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    {"action": "click", "selector": "#button"},
                ],
            },
        )

        result = _run_scenario(
            db_path, 604,
            execute_step_responses=[{"success": True, "artifacts": []}],
        )

        assert result.verdict == "pass"
        assert result.runs[0].expected_screenshots == 0
        assert result.runs[0].recorded_screenshots == 0

    def test_ac6_no_browser_requirements_skip_unaffected(self, db_path: str) -> None:
        """AC-6: items without browser requirements skip cleanly."""
        _seed_item(db_path, 605)

        patches = _patch_external_deps(db_path)
        for p in patches:
            p.start()
        try:
            result = browser_qa.execute_scenario(
                item_id=605,
                project="testproj",
                base_url="http://localhost:9999",
            )
        finally:
            for p in patches:
                p.stop()

        assert result.verdict == "pass"
        assert result.note == "no_browser_requirements"


# ---------------------------------------------------------------------------
# Data envelope unwrapping
# ---------------------------------------------------------------------------

class TestDataEnvelopeUnwrapping:
    """daemon wraps responses under a 'data' key."""

    def test_wrapped_response_extracts_artifacts(self, tmp_path: Path, db_path: str) -> None:
        """AC-01/AC-04: artifacts inside data envelope are correctly extracted."""
        _seed_item(db_path, 700)
        shot_file = tmp_path / "wrapped.png"
        shot_file.write_bytes(b"PNG")
        _seed_requirement(
            db_path, 700, "browser_smoke",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    {"action": "screenshot", "capture": True, "label": "wrapped"},
                ],
            },
        )

        result = _run_scenario(
            db_path, 700,
            execute_step_responses=[
                # navigate — flat response (no data envelope)
                {"success": True, "artifacts": []},
                # screenshot — daemon-wrapped response with data envelope
                {"success": True, "data": {"success": True, "duration_ms": 124, "artifacts": [str(shot_file)]}},
            ],
        )

        # capture success => runs[].verdict is empty + execution_status='captured'
        assert result.verdict == "pass"
        assert result.runs[0].verdict == ""
        assert result.runs[0].execution_status == "captured"
        assert result.runs[0].recorded_screenshots == 1

    def test_flat_response_still_works(self, tmp_path: Path, db_path: str) -> None:
        """AC-05: flat response shape (no data key) continues to work."""
        _seed_item(db_path, 701)
        shot_file = tmp_path / "flat.png"
        shot_file.write_bytes(b"PNG")
        _seed_requirement(
            db_path, 701, "browser_smoke",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "screenshot", "capture": True, "label": "flat"},
                ],
            },
        )

        result = _run_scenario(
            db_path, 701,
            execute_step_responses=[
                {"success": True, "artifacts": [str(shot_file)]},
            ],
        )

        # capture success => runs[].verdict is empty + execution_status='captured'
        assert result.verdict == "pass"
        assert result.runs[0].verdict == ""
        assert result.runs[0].execution_status == "captured"
        assert result.runs[0].recorded_screenshots == 1

    def test_wrapped_data_success_false_fails_step(self, db_path: str) -> None:
        """AC-06: data.success=false fails the step even when outer success=true."""
        _seed_item(db_path, 702)
        _seed_requirement(
            db_path, 702, "browser_smoke",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "screenshot", "capture": True, "label": "fail"},
                ],
            },
        )

        result = _run_scenario(
            db_path, 702,
            execute_step_responses=[
                {"success": True, "data": {"success": False, "error": "render_timeout"}},
            ],
        )

        assert result.verdict == "fail"
        assert result.runs[0].verdict == "fail"
        assert "render_timeout" in result.runs[0].errors

    def test_wrapped_no_artifacts_triggers_no_screenshot_artifact(self, db_path: str) -> None:
        """AC-02: wrapped response with empty artifacts still triggers no_screenshot_artifact."""
        _seed_item(db_path, 703)
        _seed_requirement(
            db_path, 703, "browser_smoke",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "screenshot", "capture": True, "label": "empty"},
                ],
            },
        )

        result = _run_scenario(
            db_path, 703,
            execute_step_responses=[
                {"success": True, "data": {"success": True, "artifacts": []}},
            ],
        )

        assert result.verdict == "fail"
        assert "no_screenshot_artifact" in result.runs[0].errors
