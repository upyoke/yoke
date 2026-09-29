"""No human review is requested against evidence a hosted reviewer cannot open."""

from __future__ import annotations

import pytest

from runtime.api.domain.qa_review_seed import _seed_undetermined_review
from yoke_core.domain import qa_artifact_broker, qa_evidence_portability
from yoke_core.domain.decision_requests import list_subject_requests
from yoke_core.domain.qa_evidence_portability import (
    EvidenceNotPortable,
    unservable_artifacts,
)
from yoke_core.domain.qa_review_requests import ensure_qa_review_request

LOCAL = {"artifact_id": 1, "artifact_handle": '{"backend":"local","path":"/x.png"}'}
STORED = {
    "artifact_id": 2,
    "artifact_handle": '{"backend":"s3","bucket":"b","key":"k/x.png"}',
}


@pytest.fixture
def database_door(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        qa_evidence_portability, "administered_elsewhere_env", lambda: "prod-db-admin"
    )


@pytest.fixture
def local_serving_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        qa_evidence_portability, "administered_elsewhere_env", lambda: ""
    )
    monkeypatch.setattr(qa_artifact_broker, "broker_config", lambda: None)


class TestServability:
    def test_local_universe_serves_its_own_disk(self, local_serving_build) -> None:
        assert unservable_artifacts([LOCAL, STORED]) == []

    def test_database_door_cannot_serve_local_handles(self, database_door) -> None:
        assert unservable_artifacts([LOCAL, STORED]) == [LOCAL]

    def test_hosted_tenant_cannot_serve_local_handles(self, monkeypatch) -> None:
        monkeypatch.setattr(
            qa_evidence_portability, "administered_elsewhere_env", lambda: ""
        )
        monkeypatch.setattr(qa_artifact_broker, "broker_config", lambda: object())
        assert unservable_artifacts([LOCAL, STORED]) == [LOCAL]

    def test_object_store_evidence_is_servable_everywhere(self, database_door) -> None:
        assert unservable_artifacts([STORED]) == []


def test_door_refuses_review_request_and_names_the_recovery(
    test_db, database_door
) -> None:
    seeded = _seed_undetermined_review(
        test_db, item_id=9511, plan_slug="portable-proof", decider_roles=("owner",)
    )
    requirement_id = seeded["requirement_id"]

    with pytest.raises(EvidenceNotPortable) as raised:
        ensure_qa_review_request(
            test_db, requirement_id=requirement_id, run_id=seeded["run_id"]
        )

    message = str(raised.value)
    assert f"#{seeded['artifact_id']}" in message
    assert (
        f"yoke qa artifact rehome --requirement-id {requirement_id} "
        f"--artifact-id {seeded['artifact_id']}"
    ) in message
    test_db.rollback()
    assert list_subject_requests(test_db, "qa_requirement", str(requirement_id)) == []


def test_local_universe_still_requests_review(test_db, local_serving_build) -> None:
    seeded = _seed_undetermined_review(
        test_db, item_id=9512, plan_slug="local-proof", decider_roles=("owner",)
    )

    request, created = ensure_qa_review_request(
        test_db, requirement_id=seeded["requirement_id"], run_id=seeded["run_id"]
    )

    assert created is True
    assert request is not None
    assert request["subject_context"]["artifact_count"] == 1
