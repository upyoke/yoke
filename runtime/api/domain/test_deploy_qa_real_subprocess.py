"""Drive the REAL ``db_router qa requirement-add`` subprocess seed path.

The mocked integration tests in ``test_deploy_pipeline_qa_integration`` stub
``_dispatch_db_router`` wholesale and pre-seed the row, so the actual
subprocess insert — the only seeder a push-triggered, item-less deploy run
exercises — had zero coverage. The push-lane field report (github-actions
stage auto-deploys seeding 0 requirements while operator runs seeded 1)
traced to that subprocess failing while its stderr was discarded by the
dispatch helper. These tests run the subprocess for real against the ambient
canonical-schema test DB so a regression in the insert path or its CLI
routing is caught here instead of in production.

No ``deploy_db`` fixture: that fixture installs an inline minimal schema;
these need the full ``qa_requirements`` shape the canonical schema builds
(target_env, capability_requirements, suite_id, created_at, ...), which the
conftest's ambient test DB already provides.
"""

from __future__ import annotations

import json

from yoke_core.domain import deploy_qa_recorder


def test_subprocess_insert_persists_distribution_publish_requirement():
    run_id = "run-realsub-distpub-0001"
    out = deploy_qa_recorder._dispatch_db_router(
        "qa", "requirement-add",
        "--deployment-run-id", run_id,
        "--qa-kind", "distribution_publish",
        "--qa-phase", "post_deploy",
        "--blocking-mode", "blocking",
        "--requirement-source", "flow_derived",
        "--success-policy", "Workflow completes with conclusion=success",
    )
    assert out, "real qa requirement-add subprocess returned empty stdout"

    req_id = deploy_qa_recorder.cmd_get_requirement(run_id, "distribution_publish")
    assert req_id is not None
    assert str(req_id) == out


def test_seed_from_flow_drives_real_requirement_add(monkeypatch):
    """seed-from-flow seeds a distribution-publish stage via the real subprocess.

    Only the flow-config reads are stubbed; the ``qa requirement-add`` (and the
    ``runs qa-add`` projection write) dispatch for real, matching the item-less
    CI lane where seed-from-flow is the sole seeder.
    """
    run_id = "run-realsub-seedflow-0001"
    real_db_router = deploy_qa_recorder.dispatch_db_router

    def db_router_flow_only(*args, script_dir=None):
        if "runs" in args and "get" in args and "flow" in args:
            return "flow-test"
        return real_db_router(*args, script_dir=script_dir)

    def mock_flow_db(*args, script_dir=None):
        if "stages" in args:
            return json.dumps([
                {"name": "distribution-publish",
                 "executor": "github-actions-workflow",
                 "qa_kind": "distribution_publish"},
            ])
        return ""

    monkeypatch.setattr(deploy_qa_recorder, "_dispatch_db_router", db_router_flow_only)
    monkeypatch.setattr(deploy_qa_recorder, "_dispatch_flow_domain", mock_flow_db)

    seeded = deploy_qa_recorder.cmd_seed_from_flow(run_id)
    assert seeded == 1

    req_id = deploy_qa_recorder.cmd_get_requirement(run_id, "distribution_publish")
    assert req_id is not None
