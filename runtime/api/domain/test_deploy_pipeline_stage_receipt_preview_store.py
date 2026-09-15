"""A preview producer's readback, settled by the real completion validator.

Split from ``test_deploy_pipeline_stage_receipt_store.py``, whose helpers
these reuse, to keep each file inside the authored line budget. These are
the cases a ``run_preview`` producer is written against: an observation
carrying the served URL and commit settles a receipt the scoped-QA
consumer can resolve a target from, and one missing the URL a preview
requires is refused rather than passed off as evidence.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.test_deploy_pipeline_stage_receipt_store import (
    LINEAGE,
    PREVIEW_URL,
    _dispatch,
    _install_real_store,
    _latest_receipt,
    _preview_stages,
    _seed_run,
)
from yoke_core.domain import deploy_pipeline_stage_receipt as dispatch_module
from yoke_core.domain.deployment_stage_receipts import (
    deployment_stage_receipt_for_qa,
)


def test_preview_producer_readback_settles_a_consumable_receipt(
    test_db: Any, monkeypatch
) -> None:
    """The shape a preview producer registers, proven against the store."""

    def _preview_producer(context):
        capability = str(context.stage["target"]["capability"])
        assert capability == "ephemeral-env"
        rc, diag = context.dispatch(
            dispatch_environment=context.dispatch_environment
        )
        return (
            rc,
            diag,
            dispatch_module.StageObservation(
                target_name="run-preview",
                observed_release_lineage=LINEAGE,
                observed_url=PREVIEW_URL,
            ),
        )

    monkeypatch.setitem(
        dispatch_module.RECEIPT_PRODUCERS, "run_preview", _preview_producer
    )
    _install_real_store(monkeypatch, test_db)
    stages = _preview_stages()
    _seed_run(test_db, "run-store-preview", stages, current_stage="preview-deploy")

    (rc, _diag), _dispatched = _dispatch(
        stages[0],
        stages,
        run_id="run-store-preview",
        dispatch_return=(0, f"preview served at {PREVIEW_URL}"),
    )

    assert rc == 0
    receipt = _latest_receipt(test_db, "run-store-preview", "preview-deploy")
    assert receipt is not None
    assert receipt["status"] == "ready"
    assert receipt["target_kind"] == "run_preview"
    assert receipt["observed_url"] == PREVIEW_URL
    assert receipt["observed_release_lineage"] == LINEAGE
    resolved = deployment_stage_receipt_for_qa(
        test_db,
        run_id="run-store-preview",
        source_stage="preview-deploy",
        expected_target_kind="run_preview",
        expected_target_name=None,
        expected_release_lineage=LINEAGE,
    )
    assert resolved["observed_url"] == PREVIEW_URL


def test_preview_observation_without_a_url_cannot_back_qa(
    test_db: Any, monkeypatch
) -> None:
    """A run_preview target needs the URL; the consumer says so."""

    def _urlless_producer(context):
        rc, diag = context.dispatch(
            dispatch_environment=context.dispatch_environment
        )
        return (
            rc,
            diag,
            dispatch_module.StageObservation(
                target_name="run-preview",
                observed_release_lineage=LINEAGE,
            ),
        )

    monkeypatch.setitem(
        dispatch_module.RECEIPT_PRODUCERS, "run_preview", _urlless_producer
    )
    _install_real_store(monkeypatch, test_db)
    stages = _preview_stages()
    _seed_run(test_db, "run-store-urlless", stages, current_stage="preview-deploy")

    (rc, _diag), _dispatched = _dispatch(
        stages[0],
        stages,
        run_id="run-store-urlless",
        dispatch_return=(0, "preview served"),
    )
    assert rc == 0

    from yoke_core.domain.deployment_qa_execution_target import _preview_target

    resolved = deployment_stage_receipt_for_qa(
        test_db,
        run_id="run-store-urlless",
        source_stage="preview-deploy",
        expected_target_kind="run_preview",
        expected_target_name=None,
        expected_release_lineage=LINEAGE,
    )
    with pytest.raises(ValueError, match="no observed URL"):
        _preview_target(resolved)
