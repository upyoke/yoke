"""A failed evidence upload must hand back a path its reader may open.

The capture tree lives under the machine scratch root inside the
operator's home dot-directories. A session holding an implementation-lane
claim is refused when it reads there, so a recovery recipe naming the
capture path is a recipe its own guard denies — the caller hits a second
refusal on the command the first refusal told it to run. These tests hold
the staged recovery copy to the standard the recipe implies: the operand
it names must pass the same session-cwd authority the caller runs under.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from unittest import mock

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import qa_case_execution
from yoke_core.domain.lint_session_cwd_path_authority import is_free_path
from yoke_core.domain.lint_session_cwd_validate import validate_targets
from yoke_core.domain.qa_artifacts import recovery_copy_root, stage_recovery_copy

ARTIFACT_FILENAME = "ci-run-output.txt"
EVIDENCE = "$ pytest\n[100%]\n\n[exit_code]\n0\n"
SESSION = "sid-qa-evidence-recovery"
ITEM_ID = 2453


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def lane_claimed_session(conn, tmp_path):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees" / f"YOK-{ITEM_ID}").mkdir(parents=True)
    register_machine_checkout(tmp_path / "machine-config", repo_path, 1)
    seed_item(
        conn, item_id=ITEM_ID, branch=f"YOK-{ITEM_ID}", repo_path=repo_path,
    )
    seed_item_claim(conn, SESSION, item_id=ITEM_ID)
    return SESSION


def _failing_upload_leg(case, *, actor=None):
    """Answer the run leg, then fail the artifact leg the recipe recovers."""

    def dispatch_leg(function_id: str, payload: dict) -> dict:
        if function_id == "qa.run.add":
            return {"qa_run_id": 7781}
        if function_id == "qa.artifact.add":
            raise qa_case_execution.QaCaseExecutionError(
                "qa.artifact.add failed (relay_unavailable): no route"
            )
        return {}

    return dispatch_leg


def _upload_failure_message() -> str:
    case = {
        "requirement_id": 4471,
        "item_id": ITEM_ID,
        "project": "yoke",
        "project_id": 1,
    }
    with mock.patch.object(
        qa_case_execution, "recording_leg", _failing_upload_leg,
    ):
        with pytest.raises(qa_case_execution.QaCaseExecutionError) as caught:
            qa_case_execution.record_command_run(
                case,
                performed_by="ci_run",
                raw_result="{}",
                duration_ms=12,
                verdict="pass",
                output=EVIDENCE,
                filename=ARTIFACT_FILENAME,
                metadata={},
            )
    return str(caught.value)


def _recovery_operand(message: str) -> str:
    match = re.search(r"--content-file (.+?)`", message)
    assert match, message
    return shlex.split(match.group(1))[0]


class TestStagedRecoveryCopy:
    def test_staged_copy_carries_the_evidence_bytes(self):
        staged = stage_recovery_copy(EVIDENCE.encode("utf-8"), ARTIFACT_FILENAME)
        assert staged.read_text() == EVIDENCE

    def test_staged_copy_keeps_the_artifact_filename(self):
        staged = stage_recovery_copy(EVIDENCE.encode("utf-8"), ARTIFACT_FILENAME)
        assert staged.name == ARTIFACT_FILENAME

    def test_staged_copy_lands_on_the_free_path_allowlist(self):
        staged = stage_recovery_copy(EVIDENCE.encode("utf-8"), ARTIFACT_FILENAME)
        assert is_free_path(str(staged))

    def test_temp_root_outside_the_allowlist_falls_back(self, tmp_path):
        outside = tmp_path / "not-free"
        outside.mkdir()
        with mock.patch("tempfile.gettempdir", return_value=str(outside)):
            assert is_free_path(str(recovery_copy_root()))

    def test_capture_tree_home_shape_is_not_readable(self):
        """Why the copy exists: the capture root is a home dot-directory."""
        capture = (
            Path.home() / ".yoke" / "tmp" / "yoke" / "sessions" / "s" / "runs"
            / "r" / "storage" / "qa-artifacts" / "9" / ARTIFACT_FILENAME
        )
        assert not is_free_path(str(capture))


class TestUploadFailureRecipe:
    def test_recipe_names_the_staged_copy(self):
        message = _upload_failure_message()
        operand = _recovery_operand(message)
        assert Path(operand).read_text() == EVIDENCE

    def test_recipe_operand_is_runnable_from_a_claimed_lane(
        self, conn, lane_claimed_session,
    ):
        operand = _recovery_operand(_upload_failure_message())
        verdict = validate_targets(
            conn,
            session_id=lane_claimed_session,
            targets=[operand],
            read_only=True,
            command=f"yoke qa artifact add --content-file {operand}",
        )
        assert verdict.allow, verdict.reason

    def test_message_still_names_the_capture_for_the_operator(self):
        message = _upload_failure_message()
        assert "the capture itself stays at" in message
        assert "yoke qa run complete" in message
