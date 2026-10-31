"""Requirement owners write the exact object keys their readers accept."""

import base64
import json
from unittest.mock import patch
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_qa_artifact_broker import _broker_env, _request, _seed_run
from runtime.api.domain.test_qa_plan_standalone_execution import _begin, _plan
from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_artifact_read_test_support import artifact_read_request
from yoke_cli.commands.adapters.qa_execution_subjects import _no_bytes_message
from yoke_core.domain import qa_artifact_broker as broker
from yoke_core.domain.handlers.qa_artifact_add import handle_qa_artifact_add
from yoke_core.domain.handlers.qa_artifact_read import handle_qa_artifact_read
from yoke_core.domain.qa_artifact_handle import build_artifact_key
from yoke_core.domain.qa_artifact_owner import requirement_storage_owner
from yoke_core.domain.qa_plan_management import create_plan


@pytest.mark.parametrize("subject", ["release", "item", "epic", "standalone", "member"])
def test_owner_write_and_read_return_identical_evidence(subject, tmp_path, monkeypatch):
    _broker_env(monkeypatch, tmp_path)
    stored = {}
    content = b"captured evidence"

    def sign(_config, *, operation, project, subject, run_id, filename):
        key = build_artifact_key(
            project, subject, run_id, filename, storage_prefix="tenants/7"
        )
        return broker.BrokerPresign(
            url=f"https://s3.example/{key}",
            method="PUT" if operation == "put" else "GET",
            bucket="yoke-prod-artifacts",
            key=key,
            expires_in=900,
        )

    def upload(url, *, content, **_kwargs):
        stored[url] = content

    def inline(url):
        return base64.b64encode(stored[url]).decode()

    with test_database() as conn:
        run_id = _seed_run(conn)
        requirement_id = 10
        expected_project = "other"
        if subject == "standalone":
            _plan(conn)
            execution = _begin(conn)
            requirement_id = execution["roster"][0]["requirement_id"]
            conn.execute(
                "UPDATE qa_runs SET qa_requirement_id=%s WHERE id=%s",
                (requirement_id, run_id),
            )
            expected_project = "yoke"
            expected_subject = f"standalone-{execution['id']}"
        else:
            insert_item(conn, id=43, title="Other project", project="other")
            plan = create_plan(conn, project="other", slug="evidence", name="Evidence")
            conn.execute(
                "UPDATE qa_requirements SET plan_id=%s WHERE id=10", (plan["id"],)
            )
            expected_subject = "42"
            if subject in {"release", "member"}:
                insert_deployment_run(conn, id="run-owner-proof")
                conn.execute(
                    "UPDATE qa_requirements SET item_id=NULL, deployment_run_id=%s "
                    "WHERE id=10",
                    ("run-owner-proof",),
                )
                expected_subject = "deployment-run-run-owner-proof"
                if subject == "member":
                    conn.execute(
                        "UPDATE qa_requirements SET deployment_member_item_id=42, "
                        "deployment_stage='item-qa' WHERE id=10"
                    )
                    expected_project = "yoke"
            elif subject == "epic":
                conn.execute(
                    "UPDATE qa_requirements SET item_id=NULL, epic_id=42, "
                    "task_num=1, plan_id=NULL WHERE id=10"
                )
                expected_project = "yoke"
        conn.commit()
        owner = requirement_storage_owner(conn, requirement_id)
        assert owner["project"] == expected_project
        with (
            patch.object(broker, "presign_with_broker", side_effect=sign),
            patch(
                "yoke_core.domain.qa_artifact_storage._upload_bytes", side_effect=upload
            ),
            patch("yoke_core.domain.signed_object_transfer.probe_signed_object"),
            patch(
                "yoke_core.domain.handlers.qa_artifact_read.inline_text_base64",
                side_effect=inline,
            ),
        ):
            added = handle_qa_artifact_add(
                _request(
                    "qa.artifact.add",
                    requirement_id,
                    {
                        "run_id": run_id,
                        "artifact_type": "log",
                        "filename": "evidence.log",
                        "content_type": "text/plain",
                        "content_base64": base64.b64encode(content).decode(),
                    },
                )
            )
            assert added.primary_success, added.error
            artifact_id = added.result_payload["qa_artifact_id"]
            handle = json.loads(
                conn.execute(
                    "SELECT artifact_handle FROM qa_artifacts WHERE id=%s",
                    (artifact_id,),
                ).fetchone()[0]
            )
            assert handle["key"] == (
                f"tenants/7/qa-artifacts/{expected_project}/{expected_subject}/{run_id}/evidence.log"
            )
            read = handle_qa_artifact_read(
                artifact_read_request(requirement_id, artifact_id)
            )
            assert read.primary_success, read.error
            assert read.result_payload["disposition"] == "ready"
            assert base64.b64decode(read.result_payload["content_base64"]) == content
            handle["key"] = handle["key"].replace(
                "qa-artifacts/", "qa-artifacts/wrong/"
            )
            conn.execute(
                "UPDATE qa_artifacts SET artifact_handle=%s WHERE id=%s",
                (json.dumps(handle), artifact_id),
            )
            conn.commit()
            refused = handle_qa_artifact_read(
                artifact_read_request(requirement_id, artifact_id)
            )
            assert refused.result_payload["disposition"] == "evidence_key_mismatch"
            assert "re-capture" in refused.result_payload["detail"]
            assert "differs from" in refused.result_payload["detail"]
            message = _no_bytes_message(
                SimpleNamespace(requirement_id=requirement_id, artifact_id=artifact_id),
                refused.result_payload,
            )
            assert "Re-run the QA case" in message
            assert "run `yoke qa artifact rehome" not in message
