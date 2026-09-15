"""Receipt-backed dispatch settled by the real completion validator.

``test_deploy_pipeline_stage_receipt.py`` mocks the control-plane calls to
assert what the dispatcher *asks for*; that cannot catch an ask the store
would reject. Here the control-plane helpers call the real store against a
real database, so the validator that compares observed evidence against
what the run pins gets to answer:

* a run pinning an artifact identity no producer reads back is refused
  before a receipt is ever allocated, rather than deploying and then
  failing completion, and
* an environment receipt settles and resolves as its QA stage's own
  evidence.

The ``run_preview`` cases share these helpers from
``test_deploy_pipeline_stage_receipt_preview_store.py``.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import deploy_pipeline_stage_receipt as dispatch_module
from yoke_core.domain.deploy_image_tag import canonical_image_tag
from yoke_core.domain.deployment_flow_versioning import cmd_create
from yoke_core.domain.deployment_stage_receipts import (
    allocate_deployment_stage_receipt,
    complete_deployment_stage_receipt,
    deployment_stage_receipt_for_qa,
)

LINEAGE = "c" * 40
PREVIEW_URL = "https://preview-run.example.test"
#: The health-check diagnostic that identifies this pinned candidate.
VERIFIED_BUILD = canonical_image_tag(LINEAGE)


def _preview_stages() -> list[dict[str, Any]]:
    """A preview producer and the QA stage that consumes its receipt.

    The producing execution stage carries the capability selector; the
    consuming QA target names only the kind and its source stage, which
    is what ``deployment_flow_policy`` permits on each.
    """
    return [
        {
            "name": "preview-deploy",
            "step_runner": "ephemeral-verify",
            "stage_kind": "execution",
            "scope": "run",
            "target": {"kind": "run_preview", "capability": "ephemeral-env"},
        },
        {
            "name": "preview-qa",
            "step_runner": "qa",
            "stage_kind": "qa",
            "scope": "run",
            "target": {"kind": "run_preview", "source_stage": "preview-deploy"},
            "verdict": {"mode": "agent_only"},
        },
    ]


def _environment_stages() -> list[dict[str, Any]]:
    return [
        {
            "name": "deploy-stage",
            "step_runner": "health-check",
            "stage_kind": "execution",
            "scope": "run",
        },
        {
            "name": "release-qa",
            "step_runner": "qa",
            "stage_kind": "qa",
            "scope": "run",
            "target": {
                "kind": "persistent_environment",
                "environment": "stage",
                "source_stage": "deploy-stage",
            },
            "verdict": {"mode": "agent_only"},
        },
    ]


def _seed_run(
    conn: Any,
    run_id: str,
    stages: list[dict[str, Any]],
    *,
    current_stage: str,
    artifact_identity: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
        "SELECT id,1,'stage','https://stage.example.test','{}',%s FROM sites "
        "WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO UPDATE SET url=EXCLUDED.url",
        ("2026-09-14T00:00:00Z",),
    )
    # A preview stage names the capability that says where this project
    # publishes previews, and flow creation now resolves that name against
    # the project — as it already did for a persistent environment. Seeding
    # it keeps these fixtures shaped like a real project rather than
    # tripping a reference check they are not about.
    if any(
        (stage.get("target") or {}).get("capability")
        for stage in stages
        if isinstance(stage, dict)
    ):
        conn.execute(
            "INSERT INTO project_capabilities (project_id, type, settings, created_at) "
            "VALUES (1, 'ephemeral-env', %s, %s) ON CONFLICT DO NOTHING",
            (
                '{"trigger":"github-push","preview_domain":"preview.example.test",'
                '"identity_path":"/candidate-revision"}',
                "2026-09-14T00:00:00Z",
            ),
        )
    flow_id = f"flow-{run_id}"
    cmd_create(
        conn, flow_id, "yoke", flow_id, "", json.dumps(stages), status="disabled"
    )
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "current_stage,artifact_identity,created_at) "
        "VALUES (%s,1,%s,%s,'executing',%s,%s,%s)",
        (
            run_id,
            flow_id,
            LINEAGE,
            current_stage,
            artifact_identity,
            "2026-09-14T00:00:00Z",
        ),
    )
    conn.commit()


def _latest_receipt(conn: Any, run_id: str, stage_name: str) -> dict[str, Any] | None:
    """The newest attempt for one run/stage, read straight from the table."""
    cursor = conn.execute(
        "SELECT * FROM deployment_stage_receipts WHERE run_id=%s AND stage_name=%s "
        "ORDER BY attempt_number DESC LIMIT 1",
        (run_id, stage_name),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {str(key): row[key] for key in row.keys()}


def _install_real_store(monkeypatch, conn: Any) -> None:
    """Point the dispatcher's control-plane calls at the real store."""

    def allocate(run_id, *, stage_name, correlation_id, target_kind, executor):
        receipt = allocate_deployment_stage_receipt(
            conn,
            run_id=run_id,
            stage_name=stage_name,
            correlation_id=correlation_id,
            target_kind=target_kind,
            executor=executor,
        )
        return {
            "receipt_id": int(receipt["id"]),
            "attempt_number": int(receipt["attempt_number"]),
            "correlation_id": str(receipt["correlation_id"]),
            "status": str(receipt["status"]),
        }

    def complete(run_id, *, receipt_id, correlation_id, status, **evidence):
        return complete_deployment_stage_receipt(
            conn,
            run_id=run_id,
            receipt_id=receipt_id,
            correlation_id=correlation_id,
            status=status,
            **evidence,
        )

    def latest(run_id, *, stage_name):
        return _latest_receipt(conn, run_id, stage_name)

    monkeypatch.setattr(
        dispatch_module.control_plane, "allocate_stage_receipt", allocate
    )
    monkeypatch.setattr(
        dispatch_module.control_plane, "complete_stage_receipt", complete
    )
    monkeypatch.setattr(
        dispatch_module.control_plane, "latest_stage_receipt", latest
    )


def _dispatch(stage, stages, *, run_id, dispatch_return, **overrides):
    kwargs: dict[str, Any] = dict(
        run_id=run_id,
        member_items=[],
        github_repo="owner/repo",
        project="yoke",
        project_repo_path="/tmp/repo",
        branch="main",
        first_item="",
        timeout_min=5,
        fresh=False,
        environment_name="stage",
        gate_branch="main",
        release_lineage=LINEAGE,
    )
    kwargs.update(overrides)
    import unittest.mock as mock

    with mock.patch.object(
        dispatch_module,
        "_dispatch_step_runner",
        mock.Mock(return_value=dispatch_return),
    ) as dispatched:
        result = dispatch_module.dispatch_step_runner_with_receipt(
            stage, stages=stages, **kwargs
        )
    return result, dispatched


def test_pinned_artifact_run_is_refused_without_allocating_a_receipt(
    test_db: Any, monkeypatch
) -> None:
    _install_real_store(monkeypatch, test_db)
    stages = _environment_stages()
    _seed_run(
        test_db,
        "run-store-pinned",
        stages,
        current_stage="deploy-stage",
        artifact_identity='{"digest":"sha256:pinned"}',
    )

    (rc, diag), dispatched = _dispatch(
        stages[0],
        stages,
        run_id="run-store-pinned",
        dispatch_return=(0, VERIFIED_BUILD),
        run_artifact_identity='{"digest":"sha256:pinned"}',
    )

    assert rc == 1
    assert "pins artifact identity" in diag
    dispatched.assert_not_called()
    assert (
        _latest_receipt(test_db, "run-store-pinned", "deploy-stage")
        is None
    )


def test_environment_receipt_settles_under_the_real_validator(
    test_db: Any, monkeypatch
) -> None:
    _install_real_store(monkeypatch, test_db)
    stages = _environment_stages()
    _seed_run(test_db, "run-store-env", stages, current_stage="deploy-stage")

    (rc, _diag), _dispatched = _dispatch(
        stages[0],
        stages,
        run_id="run-store-env",
        dispatch_return=(0, VERIFIED_BUILD),
    )

    assert rc == 0
    receipt = _latest_receipt(test_db, "run-store-env", "deploy-stage")
    assert receipt is not None
    assert receipt["status"] == "ready"
    assert receipt["observed_release_lineage"] == LINEAGE
    assert receipt["observed_artifact_identity"] is None
    assert receipt["executor_receipt"] == VERIFIED_BUILD
    # The scoped-QA consumer accepts it as this stage's evidence.
    resolved = deployment_stage_receipt_for_qa(
        test_db,
        run_id="run-store-env",
        source_stage="deploy-stage",
        expected_target_kind="persistent_environment",
        expected_target_name="stage",
        expected_release_lineage=LINEAGE,
    )
    assert int(resolved["id"]) == int(receipt["id"])
