"""Every captured browser outcome has retained evidence before completion."""

from contextlib import ExitStack
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.domain import browser_qa, browser_qa_requirement
from yoke_core.domain import deployment_qa_stage_case_failures as settlement
from yoke_core.domain.browser_qa_run_evidence import complete_run_with_evidence
from yoke_core.domain.browser_qa_steps import QaArtifactWriteError


def _capture(tmp_path, *, method="browser-check", failure=False, write_error=None):
    recorded, completed = [], []

    def record(run_id, requirement_id, path, content_type, artifact_type, metadata, **kw):
        if content_type != "application/json":
            return 40
        if write_error:
            raise write_error
        recorded.append({
            "run_id": run_id, "requirement_id": requirement_id,
            "content_type": content_type, "artifact_type": artifact_type,
            "payload": json.loads(Path(path).read_text()),
        })
        return 41

    def complete(*args, **kwargs):
        assert recorded or write_error
        completed.append(kwargs)

    def execute(step, *args):
        if failure:
            return {"exit_code": 2}
        if step["action"] == "screenshot":
            shot = tmp_path / "page.png"
            shot.write_bytes(b"PNG")
            return {"success": True, "artifacts": [str(shot)]}
        return {"success": True, "artifacts": []}

    steps = [{"action": "navigate", "route": "/"},
             {"action": "assert", "target": "body", "check": "visible"}]
    if method == "browser-inspection":
        steps.append({"action": "screenshot", "capture": True})
    with ExitStack() as stack:
        for name, kwargs in {
            "_record_run": {"return_value": 11},
            "_record_artifact_file": {"side_effect": record},
            "_complete_run": {"side_effect": complete},
            "open_owned_page": {"return_value": "owned-page"},
            "close_owned_page": {"return_value": None},
            "_execute_step": {"side_effect": execute},
        }.items():
            stack.enter_context(patch.object(browser_qa, name, **kwargs))
        stack.enter_context(patch.object(browser_qa_requirement, "artifact_directory", return_value=tmp_path))
        outcome = browser_qa_requirement._process_requirement(
            req_row={"id": 7, "qa_kind": "plan_case", "method_id": method,
                     "method_config": json.dumps({"steps": steps})},
            subject=1, project="example", base_url="https://example.test",
            code_identity={"sha": "a" * 40}, freshness_validated=True, sign_in={},
        )
    return outcome, recorded, completed[0]


def test_assert_only_pass_retains_counts_and_settles_item_qa(tmp_path):
    outcome, artifacts, completion = _capture(tmp_path)
    assert outcome.run_result.verdict == "pass"
    assert artifacts[0]["artifact_type"] == "evidence"
    assert artifacts[0]["content_type"] == "application/json"
    payload = artifacts[0]["payload"]
    assert payload["assertions_declared"] == payload["assertions_passed"] == 1
    assert payload["verdict"] == "pass"
    assert json.loads(completion["raw_result"])["artifact_ids"] == [41]
    assert not completion.get("capture_degraded_reason")
    assert outcome.run_result.artifact_ids == [41]
    with (
        patch.object(settlement, "scoped_cases", return_value=[{"id": 7, "plan_case_key": "assertion"}]),
        patch.object(settlement, "obligation_settled", return_value=False),
        patch.object(settlement, "_latest_verdicts", return_value={7: (11, "pass")}),
        patch.object(settlement, "qa_artifact_counts_by_run", return_value={11: {"evidence": len(artifacts)}}),
        patch("yoke_core.domain.qa_pending_agent_review.pending_review_requirements", return_value={}),
    ):
        assert settlement.case_failures(
            None, run_id="release", stage_name="item-qa", member_item_id=1,
            execution_target_digest="target",
        ) == []


@pytest.mark.parametrize("method,failure,status,verdict", [
    ("browser-inspection", False, "captured", "pending"),
    ("browser-check", True, "capture_failed", "fail"),
])
def test_inspection_and_failed_capture_retain_payload(tmp_path, method, failure, status, verdict):
    outcome, artifacts, completion = _capture(tmp_path, method=method, failure=failure)
    assert outcome.run_result.verdict == verdict
    assert outcome.run_result.execution_status == status
    assert artifacts[0]["payload"]["execution_status"] == status
    assert 41 in json.loads(completion["raw_result"])["artifact_ids"]


@pytest.mark.parametrize("error", [OSError("disk full"), QaArtifactWriteError("upload refused")])
def test_evidence_write_failure_refuses_capture_success(tmp_path, error):
    outcome, artifacts, completion = _capture(tmp_path, write_error=error)
    assert artifacts == []
    assert outcome.capture_failed
    assert completion["execution_status"] == "capture_failed"
    assert completion["verdict"] == "fail"
    assert "run_evidence_write_failed:" in outcome.run_result.errors
    assert "yoke qa case run --requirement-id 7" in outcome.run_result.errors


def test_file_write_failure_completes_as_capture_failed(tmp_path):
    with patch.object(browser_qa, "_complete_run") as complete:
        status, verdict, errors = complete_run_with_evidence(
            11, 7, artifact_dir=str(tmp_path / "missing"), verdict="pass",
            execution_status="captured", raw_result="{}", artifacts=[], artifact_ids=[],
        )
    assert (status, verdict) == ("capture_failed", "fail")
    assert "run_evidence_write_failed:" in errors
    assert complete.call_args.kwargs["execution_status"] == "capture_failed"


def test_clean_walk_evidence_is_taught_on_every_dispatch_and_harness():
    import ast
    import inspect
    from yoke_core.domain import agent_mission_brief

    tree = ast.parse(inspect.getsource(agent_mission_brief))
    prompts = [node.value for node in ast.walk(tree)
               if isinstance(node, ast.Constant) and isinstance(node.value, str)
               and "On a clean walk," in node.value]
    assert len(prompts) == 2
    for prompt in prompts:
        assert "proof of the good outcome as evidence before returning the report" in prompt
    root = Path(__file__).resolve().parents[3]
    for relative in [
        "runtime/agents/qa-walker.md",
        "runtime/harness/claude/agents/yoke-qa-walker.md",
        "runtime/harness/codex/agents/yoke-qa-walker.toml",
        "runtime/harness/cursor/agents/yoke-qa-walker.md",
    ]:
        text = (root / relative).read_text()
        assert "On a clean walk, attach one deliberate proof of the good outcome as `evidence`" in text
        assert "before returning the report, within the same artifact limit" in text


def test_assert_only_evidence_persists_and_settles_without_manual_attach(tmp_path):
    from runtime.api.domain.browser_qa_test_helpers import (
        _browser_check_steps, _placeholder, _run_scenario, _seed_item, _seed_requirement,
    )
    from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

    with init_test_db(tmp_path) as db_path:
        _seed_item(db_path, 100)
        requirement_id = _seed_requirement(
            db_path, 100, "browser-check", {"steps": _browser_check_steps()},
        )
        outcome = _run_scenario(
            db_path, 100, execute_step_responses=[{"success": True, "artifacts": []}],
        )
        run = outcome.runs[0]
        assert run.verdict == "pass"
        conn = connect_test_db(db_path)
        try:
            marker = _placeholder(conn)
            row = conn.execute(
                f"SELECT artifact_type,content_type FROM qa_artifacts WHERE qa_run_id={marker}",
                (run.qa_run_id,),
            ).fetchone()
            assert tuple(row) == ("evidence", "application/json")
            row = conn.execute(
                f"SELECT capture_degraded_reason FROM qa_runs WHERE id={marker}",
                (run.qa_run_id,),
            ).fetchone()
            assert row[0] is None
            with (
                patch.object(settlement, "scoped_cases", return_value=[{
                    "id": requirement_id, "plan_case_key": "assertion",
                }]),
                patch.object(settlement, "obligation_settled", return_value=False),
                patch.object(settlement, "_latest_verdicts", return_value={
                    requirement_id: (run.qa_run_id, run.verdict),
                }),
                patch("yoke_core.domain.qa_pending_agent_review.pending_review_requirements", return_value={}),
            ):
                assert settlement.case_failures(
                    conn, run_id="release", stage_name="item-qa", member_item_id=100,
                    execution_target_digest="target",
                ) == []
        finally:
            conn.close()
