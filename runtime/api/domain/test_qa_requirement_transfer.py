"""Ownership transfers keep the case, validate both claims and retain audit."""

import pytest
from runtime.api.domain.test_dash_post_deploy_review_isolation import _insert_dash
from runtime.api.fixtures.deployment_admitted_case_fixture import intake_requirement
from yoke_core.domain import qa_requirement_transfer as transfer
from yoke_core.domain.item_json_sections import read_json_section


def _setup(conn, monkeypatch):
    for item_id in (2390, 2391):
        _insert_dash(conn, item_id=item_id, status="release")
    requirement_id = intake_requirement(conn, item_id=2390)
    monkeypatch.setattr(
        transfer, "get_claim_for_work_unit", lambda *a, **k: {"session_id": "owner"}
    )
    ref = conn.execute(
        "SELECT public_ref FROM item_refs WHERE item_id=2391"
    ).fetchone()[0]
    return requirement_id, ref


def _move(conn, rid, destination):
    return transfer.transfer_requirement(
        conn,
        requirement_id=rid,
        destination=destination,
        transition="release",
        rationale="Destination owns the check",
        session_id="owner",
        request_id="transfer-test",
    )


def test_transfer_preserves_case_identity_and_audits_both_items(test_db, monkeypatch):
    rid, ref = _setup(test_db, monkeypatch)
    receipt = _move(test_db, rid, ref)
    row = test_db.execute(
        "SELECT item_id,method_id FROM qa_requirements WHERE id=%s", (rid,)
    ).fetchone()
    assert row["item_id"] == 2391
    assert row["method_id"] == "browser-inspection"
    assert receipt["from_item_id"] == 2390
    for item_id in (2390, 2391):
        audit = read_json_section(
            test_db, item_id=item_id, section="QA requirement transfer transfer-test"
        )
        assert audit["requirement_id"] == rid
        assert audit["rationale"] == "Destination owns the check"


def test_transfer_refuses_methodless_ac_derived_without_mutation(test_db, monkeypatch):
    rid, ref = _setup(test_db, monkeypatch)
    test_db.execute(
        "UPDATE qa_requirements SET method_id=NULL,qa_kind='ac_verification',requirement_source='ac_derived' WHERE id=%s",
        (rid,),
    )
    with pytest.raises(ValueError, match="requirement_proof_required"):
        _move(test_db, rid, ref)
    assert (
        test_db.execute(
            "SELECT item_id FROM qa_requirements WHERE id=%s", (rid,)
        ).fetchone()[0]
        == 2390
    )


def test_transfer_requires_destination_claim(test_db, monkeypatch):
    rid, ref = _setup(test_db, monkeypatch)
    monkeypatch.setattr(
        transfer,
        "get_claim_for_work_unit",
        lambda *a, **k: (
            {"session_id": "other"}
            if k["item_id"] == "2391"
            else {"session_id": "owner"}
        ),
    )
    with pytest.raises(ValueError, match="no work claim on item 2391"):
        _move(test_db, rid, ref)


def test_transfer_refuses_recorded_history(test_db, monkeypatch):
    rid, ref = _setup(test_db, monkeypatch)
    test_db.execute("UPDATE qa_requirements SET waived_at=now() WHERE id=%s", (rid,))
    with pytest.raises(ValueError, match="settled or executed"):
        _move(test_db, rid, ref)


def test_transfer_registry_has_claim_policy_and_serving_floor():
    from yoke_core.domain import yoke_function_registry
    from yoke_cli.commands.registry_qa import QA_SUBCOMMAND_REGISTRY

    from yoke_core.domain.handlers.__init_register__ import register_all_handlers

    register_all_handlers()
    entry = next(
        e
        for e in yoke_function_registry.list_entries()
        if e.function_id == "qa.requirement.transfer"
    )
    assert entry.claim_required_kind == "qa_subject"
    assert entry.minimum_serving_version == "next-release"
    assert (
        QA_SUBCOMMAND_REGISTRY[("qa", "requirement", "transfer")][0]
        == entry.function_id
    )


def test_transfer_invalid_destination_stage_preserves_owner(test_db, monkeypatch):
    rid, ref = _setup(test_db, monkeypatch)
    with pytest.raises(ValueError):
        transfer.transfer_requirement(
            test_db,
            requirement_id=rid,
            destination=ref,
            transition="nonexistent",
            rationale="Destination owns the check",
            session_id="owner",
            request_id="invalid-stage",
        )
    assert (
        test_db.execute(
            "SELECT item_id FROM qa_requirements WHERE id=%s", (rid,)
        ).fetchone()[0]
        == 2390
    )
    assert (
        read_json_section(
            test_db, item_id=2391, section="QA requirement transfer invalid-stage"
        )
        is None
    )


def test_review_credit_survives_methodless_ownership_transfer(test_db, monkeypatch):
    from runtime.api.fixtures.backlog_inserts import insert_item
    from yoke_core.domain.qa_workflow_binding_validation import item_transition_for_gate

    for item_id in (2390, 2391):
        insert_item(test_db, id=item_id, title="Manual acceptance", workflow_id="epic")
    transition = item_transition_for_gate(
        test_db, item_id=2391, gate_id="qa_verification"
    )
    rid = test_db.execute(
        "INSERT INTO qa_requirements(item_id,qa_kind,qa_phase,blocking_mode,workflow_transition_id,created_at) VALUES (2390,'ac_verification','verification','blocking',%s,now()) RETURNING id",
        (transition,),
    ).fetchone()[0]
    ref = test_db.execute(
        "SELECT public_ref FROM item_refs WHERE item_id=2391"
    ).fetchone()[0]
    monkeypatch.setattr(
        transfer, "get_claim_for_work_unit", lambda *a, **k: {"session_id": "owner"}
    )
    receipt = transfer.transfer_requirement(
        test_db,
        requirement_id=rid,
        destination=ref,
        transition=transition,
        rationale="Destination owns the manual review",
        session_id="owner",
        request_id="manual-transfer",
    )
    assert receipt["to_item_id"] == 2391
    assert (
        test_db.execute(
            "SELECT method_id FROM qa_requirements WHERE id=%s", (rid,)
        ).fetchone()[0]
        is None
    )
