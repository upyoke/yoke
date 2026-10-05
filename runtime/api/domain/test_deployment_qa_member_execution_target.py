"""Member destinations retain receipt authority and same-project identity."""

import json

import pytest

from yoke_contracts.machine_qa_case_target import case_target_mismatches
from runtime.api.domain.test_deployment_qa_cross_project_members import (
    MEMBER,
    OTHER,
    RUN,
    _ready,
)
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
    validate_deployment_execution_target,
)
from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject
from yoke_core.domain.qa_execution_environment_target import (
    canonical_target,
    require_case_target,
    target_digest,
)


def _subject(conn):
    return deployment_qa_stage_subject(
        conn, run_id=RUN, stage_name="item-qa", member_item_id=MEMBER
    )


def test_cross_project_member_uses_own_identity_endpoints_and_receipt(test_db):
    _ready(test_db)
    test_db.execute(
        "UPDATE deployment_stage_receipts SET observed_url=%s WHERE run_id=%s",
        ("https://carried.example.test", RUN),
    )
    subject = _subject(test_db)
    target = deployment_qa_execution_target(test_db, subject)

    assert target["project"] == {"id": OTHER, "slug": "carried", "name": "Carried"}
    assert target["endpoints"]["app_url"] == "https://carried.example.test"
    assert target["observed_url"] == "https://carried.example.test"
    assert target["deployment"]["run_id"] == RUN
    assert target["deployment"]["member_item_id"] == MEMBER
    assert (
        target["observation"]["observed_release_lineage"] == subject["release_lineage"]
    )
    require_case_target({"project_id": OTHER, "target_env": "stage"}, target)
    assert case_target_mismatches(target, project_id=OTHER, project="carried") == []
    validate_deployment_execution_target(
        test_db,
        {
            "deployment_run_id": RUN,
            "deployment_stage": "item-qa",
            "deployment_member_item_id": MEMBER,
            "execution_target": target,
        },
    )


def test_member_does_not_reuse_a_target_frozen_for_run_owner(test_db, monkeypatch):
    _ready(test_db)
    subject = _subject(test_db)
    wrong = deployment_qa_execution_target(
        test_db, {**subject, "member_project_id": None}
    )
    from yoke_core.domain import deployment_qa_execution_target as targets

    monkeypatch.setattr(
        targets, "first_materialized_execution_target", lambda *a, **k: wrong
    )
    corrected = deployment_qa_execution_target(test_db, subject)
    assert corrected["project"]["id"] == OTHER
    assert corrected["endpoints"]["app_url"] == "https://carried.example.test"
    assert corrected["observation"] == wrong["observation"]


@pytest.mark.parametrize("missing", ["environment", "receipt_endpoint", "preview"])
def test_member_without_matching_deployed_destination_refuses(test_db, missing):
    _ready(test_db)
    subject = _subject(test_db)
    if missing == "environment":
        test_db.execute(
            "DELETE FROM environments WHERE project_id=%s AND name='stage'", (OTHER,)
        )
    elif missing == "receipt_endpoint":
        test_db.execute(
            "UPDATE deployment_stage_receipts SET observed_url=%s WHERE run_id=%s",
            ("https://preview.example.test", RUN),
        )
    else:
        subject["stage"]["target"]["kind"] = "run_preview"
    with pytest.raises(ValueError, match="deployment_member_target_missing"):
        deployment_qa_execution_target(test_db, subject)


def test_same_project_and_run_scope_keep_original_target_bytes(test_db):
    _ready(test_db, same_project=True)
    subject = _subject(test_db)
    target = deployment_qa_execution_target(test_db, subject)
    # A subject without member-project selection is the previous resolution path.
    original = deployment_qa_execution_target(
        test_db, {**subject, "member_project_id": None}
    )
    assert canonical_target(target) == canonical_target(original)
    assert target_digest(target) == target_digest(original)
    run_subject = {**subject, "member_project_id": None, "member_item_id": None}
    run_target = deployment_qa_execution_target(test_db, run_subject)
    assert run_target == {
        **target,
        "deployment": {**target["deployment"], "member_item_id": None},
    }


def test_existing_same_project_frozen_target_keeps_bytes_after_settings_edit(test_db):
    _ready(test_db, same_project=True, cases=True)
    from yoke_core.domain.deployment_qa_stage_materialization import (
        materialize_deployment_qa_stage,
    )

    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
    )
    raw = test_db.execute(
        "SELECT execution_target_json FROM qa_requirements "
        "WHERE deployment_run_id=%s AND deployment_member_item_id=%s LIMIT 1",
        (RUN, MEMBER),
    ).fetchone()[0]
    test_db.execute(
        "UPDATE environments SET url='https://changed.example.test' WHERE project_id=1"
    )
    frozen = json.loads(raw)
    assert canonical_target(
        deployment_qa_execution_target(test_db, _subject(test_db))
    ) == canonical_target(frozen)
