"""In-process coverage for deployment member-item stamps.

Exercises ``deployment_item_stamp.record`` against a seeded Postgres
authority, including a non-default-project item whose public sequence
differs from ``items.id``. A stamp addressed by integer id must land on
that row — never on a default-project sequence collision.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.handlers import deployment_item_stamp as stamp


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _item_envelope(item_id, payload):
    return FunctionCallRequest(
        function="deployment_item_stamp.record",
        actor=ActorContext(actor_id=None, session_id="s-deploy-stamp"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
    )


def _scalar(db, sql, params):
    conn = connect_test_db(db)
    try:
        row = conn.execute(sql, params).fetchone()
    finally:
        conn.close()
    return None if row is None else row[0]


class TestDeploymentItemStamp:
    def test_stamps_deploy_stage_on_non_default_project_item(self, db):
        item_id = 9001
        conn = connect_test_db(db)
        try:
            insert_item(
                conn,
                id=item_id,
                project="externalwebapp",
                project_sequence=12,
                source=str(seed_human_actor(conn)),
            )
        finally:
            conn.close()

        outcome = stamp.handle_deployment_item_stamp(
            _item_envelope(item_id, {"field": "deploy_stage", "value": "warm-up"})
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["verified"] is True
        assert outcome.result_payload["item_id"] == item_id
        stamp.DeploymentItemStampResponse(**outcome.result_payload)
        assert _scalar(
            db, "SELECT deploy_stage FROM items WHERE id = %s", (item_id,)
        ) == "warm-up"

    def test_stamps_deployed_to_and_reads_previous(self, db):
        item_id = 9002
        conn = connect_test_db(db)
        try:
            insert_item(
                conn,
                id=item_id,
                project="externalwebapp",
                project_sequence=13,
                deployed_to="stage",
                source=str(seed_human_actor(conn)),
            )
        finally:
            conn.close()

        outcome = stamp.handle_deployment_item_stamp(
            _item_envelope(item_id, {"field": "deployed_to", "value": "prod"})
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["previous_value"] == "stage"
        assert _scalar(
            db, "SELECT deployed_to FROM items WHERE id = %s", (item_id,)
        ) == "prod"

    def test_missing_item_refuses_without_write(self, db):
        outcome = stamp.handle_deployment_item_stamp(
            _item_envelope(40404, {"field": "deploy_stage", "value": "complete"})
        )
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "item_not_found"

    def test_unknown_field_refuses(self, db):
        outcome = stamp.handle_deployment_item_stamp(
            _item_envelope(1, {"field": "status", "value": "release"})
        )
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "field_not_stampable"

    def test_missing_target_item_id_refuses(self, db):
        request = FunctionCallRequest(
            function="deployment_item_stamp.record",
            actor=ActorContext(actor_id=None, session_id="s-deploy-stamp"),
            target=TargetRef(kind="item", item_ref="EXT-12"),
            payload={"field": "deploy_stage", "value": "complete"},
        )
        outcome = stamp.handle_deployment_item_stamp(request)
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "target_invalid"
