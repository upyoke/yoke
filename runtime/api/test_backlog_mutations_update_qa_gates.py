"""ExecuteUpdate sub-scenarios: QA-gate blockers on lifecycle transitions.

Each test seeds an unsatisfied (or stale) QA requirement and asserts that
the corresponding lifecycle transition is denied with the expected
``GATE_QA_*`` error_code, leaving status unchanged. The refusals come from
the composed ``qa_verification`` gate each pinned workflow version declares
for the stage, so a workflow that declares no such gate for a stage reaches
it with no QA rows at all.
"""

from __future__ import annotations

import io
import os
from unittest import mock

from runtime.api.backlog_mutations_test_helpers import (
    _item_field,
    _patch_externals,
    _seed_item,
    _seed_qa_artifact,
    _seed_qa_requirement,
    _seed_qa_run,
    tmp_db,  # noqa: F401,F811 — re-exported fixture
)
from yoke_core.domain import backlog
from yoke_core.domain.qa_gates import LatestCodeRef


class TestExecuteUpdate:
    """ExecuteUpdate sub-scenarios: QA gates."""

    def test_implemented_blocks_unsatisfied_blocking_verification_reqs(self, tmp_db):  # noqa: F811
        _seed_item(tmp_db, id=10, status="reviewed-implementation")
        _seed_qa_requirement(
            tmp_db,
            item_id=10,
            qa_kind="plan_case",
            success_policy='{"type":"browser_scenario"}',
        )
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(
                 os.environ,
                 {"YOKE_DB": tmp_db, "YOKE_CLAIM_BYPASS": "test-bypass"},
             ):
            result = backlog.execute_update(
                item_id=10,
                field="status",
                value="implemented",
                out=out,
            )

        assert result["success"] is False
        assert result["error_code"] == "GATE_QA_IMPLEMENTED"
        assert _item_field(tmp_db, 10, "status") == "reviewed-implementation"

    def test_release_blocks_unsatisfied_blocking_verification_reqs(self, tmp_db):  # noqa: F811
        _seed_item(tmp_db, id=10, status="implemented")
        _seed_qa_requirement(
            tmp_db,
            item_id=10,
            qa_kind="plan_case",
            success_policy='{"type":"browser_scenario"}',
        )
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(
                 os.environ,
                 {"YOKE_DB": tmp_db, "YOKE_CLAIM_BYPASS": "test-bypass"},
             ):
            result = backlog.execute_update(
                item_id=10,
                field="status",
                value="release",
                out=out,
            )

        assert result["success"] is False
        assert result["error_code"] == "GATE_QA_RELEASE"
        assert _item_field(tmp_db, 10, "status") == "implemented"

    def test_dash_reviewing_implementation_needs_no_qa_requirements(self, tmp_db):  # noqa: F811
        """Dash declares no ``qa_verification`` gate at that stage."""
        _seed_item(tmp_db, id=10, status="implementing", workflow_id="dash")
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(
                 os.environ,
                 {"YOKE_DB": tmp_db, "YOKE_CLAIM_BYPASS": "test-bypass"},
             ):
            result = backlog.execute_update(
                item_id=10,
                field="status",
                value="reviewing-implementation",
                out=out,
            )

        assert result["success"] is True, result
        assert _item_field(tmp_db, 10, "status") == "reviewing-implementation"

    def test_implemented_blocks_browser_pass_without_artifact(self, tmp_db):  # noqa: F811
        _seed_item(tmp_db, id=10, status="reviewed-implementation")
        req_id = _seed_qa_requirement(
            tmp_db,
            item_id=10,
            qa_kind="plan_case",
            success_policy='{"type":"browser_scenario"}',
        )
        _seed_qa_run(
            tmp_db,
            requirement_id=req_id,
            performed_by="browser_substrate",
            verdict="pass",
        )
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(
                 os.environ,
                 {"YOKE_DB": tmp_db, "YOKE_CLAIM_BYPASS": "test-bypass"},
             ):
            result = backlog.execute_update(
                item_id=10,
                field="status",
                value="implemented",
                out=out,
            )

        assert result["success"] is False
        assert result["error_code"] == "GATE_QA_IMPLEMENTED"
        assert "substrate evidence" in result["error"]
        assert _item_field(tmp_db, 10, "status") == "reviewed-implementation"

    def test_done_blocks_unsatisfied_blocking_requirements(self, tmp_db):  # noqa: F811
        _seed_item(tmp_db, id=10, status="release")
        _seed_qa_requirement(
            tmp_db,
            item_id=10,
            qa_kind="plan_case",
            success_policy='{"type":"browser_scenario"}',
        )
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(
                 os.environ,
                 {"YOKE_DB": tmp_db, "YOKE_CLAIM_BYPASS": "test-bypass"},
             ):
            result = backlog.execute_update(
                item_id=10,
                field="status",
                value="done",
                done_nonce_verified=True,
                out=out,
            )

        assert result["success"] is False
        assert result["error_code"] == "GATE_QA_DONE"
        assert _item_field(tmp_db, 10, "status") == "release"

    def test_reviewed_implementation_blocks_browser_pass_without_artifact(self, tmp_db):  # noqa: F811
        _seed_item(tmp_db, id=10, status="reviewing-implementation")
        req_id = _seed_qa_requirement(
            tmp_db,
            item_id=10,
            qa_kind="plan_case",
            success_policy='{"type":"browser_scenario"}',
        )
        _seed_qa_run(
            tmp_db,
            requirement_id=req_id,
            performed_by="browser_substrate",
            verdict="pass",
        )
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(
                 os.environ,
                 {"YOKE_DB": tmp_db, "YOKE_CLAIM_BYPASS": "test-bypass"},
             ):
            result = backlog.execute_update(
                item_id=10,
                field="status",
                value="reviewed-implementation",
                out=out,
            )

        assert result["success"] is False
        assert result["error_code"] == "GATE_QA_REVIEWED_IMPLEMENTATION"
        assert "substrate evidence" in result["error"]
        assert _item_field(tmp_db, 10, "status") == "reviewing-implementation"

    def test_release_blocks_browser_pass_against_stale_sha(self, tmp_db, tmp_path):  # noqa: F811
        _seed_item(tmp_db, id=10, status="implemented", project="testproj")
        req_id = _seed_qa_requirement(
            tmp_db,
            item_id=10,
            qa_kind="plan_case",
            success_policy='{"type":"browser_scenario"}',
        )
        run_id = _seed_qa_run(
            tmp_db,
            requirement_id=req_id,
            performed_by="browser_substrate",
            verdict="pass",
            raw_result='{"code_identity":{"branch":"YOK-10","sha":"oldsha"}}',
            created_at="2024-01-01T00:00:00Z",
        )
        artifact = tmp_path / "release-shot.png"
        artifact.write_bytes(b"PNG")
        _seed_qa_artifact(tmp_db, run_id=run_id, artifact_path=str(artifact))
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch(
                 "yoke_core.domain.qa_gates._resolve_latest_code_ref",
                 return_value=LatestCodeRef(
                     branch="YOK-10",
                     sha="freshsha",
                     timestamp="2025-01-01T00:00:00Z",
                 ),
             ), \
             mock.patch.dict(
                 os.environ,
                 {"YOKE_DB": tmp_db, "YOKE_CLAIM_BYPASS": "test-bypass"},
             ):
            result = backlog.execute_update(
                item_id=10,
                field="status",
                value="release",
                out=out,
            )

        assert result["success"] is False
        assert result["error_code"] == "GATE_QA_RELEASE"
        assert "Latest SHA: freshsha" in result["error"]
        assert _item_field(tmp_db, 10, "status") == "implemented"
