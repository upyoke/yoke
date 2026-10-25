"""Method facts stay bounded; only explicit full reads enumerate plans."""

from unittest.mock import patch

import pytest

from runtime.api.cli.test_yoke_operations_cli_qa_catalog import _run
from runtime.api.domain.handlers.test_qa_method_session_project import _request
from runtime.api.qa_catalog_test_support import create_release_readiness_plan
from yoke_core.domain.handlers.qa_catalog_reads import handle_method_get
from yoke_core.domain.item_posture_validation import ItemPostureError, _verification
from yoke_core.domain.qa_catalog_reads import get_method
from yoke_core.domain.qa_method_management import register_project_method


def test_default_method_detail_never_reads_related_plans(test_db):
    create_release_readiness_plan(test_db)
    with patch(
        "yoke_core.domain.qa_catalog_reads.read_method_related_plans",
        side_effect=AssertionError("default detail must not enumerate plans"),
    ):
        method = get_method(test_db, method_id="command", project="yoke")
        outcome = handle_method_get(
            _request(
                "qa.method.get", {"method_id": "command", "project": "yoke"}, "reader"
            )
        )
    assert "plans" not in method
    assert method["used_by_plan_count"] == 1
    assert method["runner_id"] == "worktree_run"
    assert outcome.primary_success
    assert outcome.result_payload["method"] == method


def test_full_method_detail_explicitly_reads_related_plans(test_db):
    plan = create_release_readiness_plan(test_db)
    outcome = handle_method_get(
        _request(
            "qa.method.get",
            {"method_id": "command", "project": "yoke", "detail": "full"},
            "reader",
        )
    )
    assert outcome.primary_success
    method = outcome.result_payload["method"]
    assert method["used_by_plan_count"] == 1
    assert [row["id"] for row in method["plans"]] == [plan["id"]]


def test_method_full_flag_dispatches_full_detail():
    result, request = _run("qa", "method", "get", "command", "--full")
    assert result == 0
    assert request.payload == {"method_id": "command", "detail": "full"}


def test_ad_hoc_posture_checks_only_method_existence(test_db):
    with patch(
        "yoke_core.domain.qa_catalog_reads.list_methods",
        side_effect=AssertionError("posture must not read the method catalog"),
    ):
        assert _verification(
            test_db, project_id=1, raw={"kind": "ad_hoc", "method_id": "command"}
        ) == {"kind": "ad_hoc", "method_id": "command"}
        with pytest.raises(ItemPostureError, match="not found"):
            _verification(
                test_db,
                project_id=1,
                raw={"kind": "ad_hoc", "method_id": "missing-method"},
            )


def test_ad_hoc_posture_rejects_another_projects_method(test_db):
    method = register_project_method(
        test_db,
        project="externalwebapp",
        slug="external-proof",
        name="External",
        description="External proof",
        runner_id="worktree_run",
        verdict_path="automatic",
        verdict_contract="Pass",
        evidence_contract="Log",
    )
    with pytest.raises(ItemPostureError, match="not found"):
        _verification(
            test_db,
            project_id=1,
            raw={"kind": "ad_hoc", "method_id": method["id"]},
        )
