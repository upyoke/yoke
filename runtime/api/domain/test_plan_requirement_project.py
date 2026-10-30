"""Plan-backed case execution and evidence share one project precedence."""

import json
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_deployment_qa_plan_groups import (
    MEMBERS, RUN, _seed,
)
from runtime.api.qa_artifact_read_test_support import artifact_read_request
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain import db_helpers
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
from yoke_core.domain.function_target_row_project import resolve_qa_requirement_project
from yoke_core.domain.qa_case_execution_context import get_case_execution_context
from yoke_core.domain.qa_case_execution import _browser_result
from yoke_core.domain.qa_execution_environment_target import target_digest
from yoke_core.domain.browser_qa_deployment_identity import resolve_run_pinned_source
from yoke_core.domain.handlers import qa_artifact_read, qa_reads
from yoke_core.domain.qa_activity_selection import ACTIVITY_SOURCE


class Borrowed:
    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


@pytest.mark.parametrize("attached", [False, True])
def test_plan_project_drives_case_and_all_evidence_reads(test_db, monkeypatch, attached):
    plan = _seed(test_db)
    [rid] = ensure_groups(test_db, RUN, "item-qa")
    test_db.execute("UPDATE qa_plans SET project_id=2 WHERE id=%s", (plan,))
    target = json.loads(test_db.execute(
        "SELECT execution_target_json FROM qa_requirements WHERE id=%s", (rid,),
    ).fetchone()[0])
    target["project"] = {"id": 2, "slug": "externalwebapp", "name": "ExternalWebapp"}
    test_db.execute(
        "UPDATE qa_requirements SET execution_target_json=%s,execution_target_digest=%s,"
        "item_id=%s,deployment_run_id=%s,deployment_stage=%s WHERE id=%s",
        (json.dumps(target), target_digest(target), MEMBERS[0] if attached else None,
         None if attached else RUN, None if attached else "item-qa", rid),
    )
    run = test_db.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,created_at) "
        "VALUES (%s,'worktree_run','command','pass',clock_timestamp()) RETURNING id", (rid,),
    ).fetchone()[0]
    artifact = test_db.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,artifact_handle,created_at) "
        "VALUES (%s,'output','text/plain',%s,clock_timestamp()) RETURNING id",
        (run, json.dumps({"backend": "local", "path": "qa/result.txt"})),
    ).fetchone()[0]
    test_db.commit()
    monkeypatch.setattr(db_helpers, "connect", lambda: Borrowed(test_db))
    monkeypatch.setattr("yoke_core.domain.qa_case_execution_context.resolve_source_lane", lambda *a, **k: {})
    case = get_case_execution_context(test_db, requirement_id=rid)
    assert (case["project_id"], case["project"]) == (2, "externalwebapp")
    assert resolve_qa_requirement_project(test_db, rid) == (2, "externalwebapp")
    assert test_db.execute("SELECT pr.id " + ACTIVITY_SOURCE + " WHERE q.id=%s", (rid,)).fetchone()[0] == 2
    # The source resolver also serves historical rows without a frozen target.
    test_db.execute(
        "UPDATE qa_requirements SET execution_target_json=NULL,execution_target_digest=NULL WHERE id=%s", (rid,),
    )
    test_db.execute("UPDATE qa_requirements SET item_id=NULL,deployment_run_id=%s WHERE id=%s", (RUN, rid))
    assert resolve_run_pinned_source(test_db, RUN, requirement_id=rid)["project"] == "externalwebapp"
    if attached:
        test_db.execute("UPDATE qa_requirements SET item_id=%s,deployment_run_id=NULL WHERE id=%s", (MEMBERS[0], rid))
    calls = []
    monkeypatch.setattr("yoke_core.domain.browser_qa.execute_scenario", lambda **kw: (
        calls.append(kw) or SimpleNamespace(to_json=lambda: '{}')
    ))
    _browser_result(case, base_url="https://example.test", expected_branch=None, expected_sha=None)
    assert calls[0]["project"] == "externalwebapp"
    response = qa_reads.handle_qa_run_get(FunctionCallRequest(
        function="qa.run.get", actor=ActorContext(actor_id="2", session_id="project-read"),
        target=TargetRef(kind="global", project_id="externalwebapp"), payload={"run_id": run},
    ))
    assert response.primary_success, response.error
    assert response.result_payload["run"]["id"] == run
    monkeypatch.setattr(qa_artifact_read, "_local_result", lambda row, handle: {"owner": row["project_id"]})
    response = qa_artifact_read.handle_qa_artifact_read(artifact_read_request(rid, artifact))
    assert response.primary_success, response.error
    assert response.result_payload["owner"] == 2
