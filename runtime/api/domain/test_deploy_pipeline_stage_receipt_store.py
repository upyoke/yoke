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

from runtime.api.domain.deploy_pipeline_stage_receipt_store_test_support import (
    LINEAGE as LINEAGE,
    PREVIEW_URL as PREVIEW_URL,
    _dispatch as _dispatch,
    _install_real_store as _install_real_store,
    _latest_receipt as _latest_receipt,
    _preview_stages as _preview_stages,
    _seed_run as _seed_run,
)


from typing import Any

from yoke_core.domain.deploy_image_tag import canonical_image_tag
from yoke_core.domain.deployment_stage_receipts import (
    deployment_stage_receipt_for_qa,
)

#: The health-check diagnostic that identifies this pinned candidate.
VERIFIED_BUILD = canonical_image_tag(LINEAGE)


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
