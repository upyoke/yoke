"""qa.artifact.presign — bucket resolution + presigned PUT minting."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from yoke_core.domain.handlers import qa_artifact_presign
from yoke_core.domain.s3_presign import AwsCredentials
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement
from runtime.api.fixtures.pg_testdb import test_database


_CREDS = AwsCredentials(
    access_key_id="AKIDEXAMPLE", secret_access_key="secret",
)


def _request(payload=None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="qa.artifact.presign",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="qa_requirement", qa_requirement_id=10),
        payload=payload or {},
    )


def _seed(
    conn,
    *,
    target_env=None,
    env_buckets=None,
    region="us-east-1",
    with_run: bool = True,
) -> None:
    # The minimal fixture schema carries no sites/environments tables;
    # create them in the production shape (projects_restart_schema).
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sites ("
        "id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, name TEXT NOT NULL,"
        " description TEXT, created_at TEXT NOT NULL,"
        " settings TEXT DEFAULT '{}')"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS environments ("
        "id TEXT PRIMARY KEY, site TEXT NOT NULL, name TEXT NOT NULL,"
        " url TEXT, deploy_method TEXT, deploy_command TEXT,"
        " health_check_url TEXT, config_notes TEXT, last_deployed_at TEXT,"
        " created_at TEXT NOT NULL, settings TEXT DEFAULT '{}')"
    )
    insert_item(conn, id=42, title="T", status="reviewing-implementation")
    insert_qa_requirement(
        conn, id=10, item_id=42, qa_kind="browser_smoke",
        qa_phase="verification", blocking_mode="blocking",
        success_policy="{}", target_env=target_env,
    )
    if with_run:
        conn.execute(
            "INSERT INTO qa_runs (id, qa_requirement_id, executor_type, "
            "qa_kind, created_at) "
            "VALUES (77, 10, 'browser_substrate', 'browser_smoke', "
            "'2026-06-12T00:00:00Z')",
        )
    conn.execute(
        "INSERT INTO sites (id, project_id, name, created_at) "
        "VALUES ('site-1', 1, 'core', '2026-06-12T00:00:00Z')",
    )
    for name, bucket in (env_buckets or {}).items():
        settings = json.dumps({"artifacts": {"bucket": bucket}}) if bucket else "{}"
        conn.execute(
            "INSERT INTO environments (id, site, name, settings, created_at) "
            "VALUES (%s, 'site-1', %s, %s, '2026-06-12T00:00:00Z')",
            (f"env-{name}", name, settings),
        )
    if region:
        conn.execute(
            "INSERT INTO project_capabilities (project_id, type, settings) "
            "VALUES (1, 'aws-admin', %s)",
            (json.dumps({"region": region}),),
        )
    conn.commit()


class TestPresignHappyPath(unittest.TestCase):
    def test_mints_put_url_and_matching_handle(self):
        with test_database() as conn:
            _seed(conn, env_buckets={"prod": "yoke-prod-artifacts"})
            with patch.object(
                qa_artifact_presign, "_capability_credentials",
                return_value=_CREDS,
            ):
                outcome = qa_artifact_presign.handle_qa_artifact_presign(
                    _request({
                        "run_id": 77, "filename": "home.png",
                        "content_type": "image/png",
                    }),
                )
        self.assertTrue(outcome.primary_success, outcome.error)
        result = outcome.result_payload
        self.assertEqual(result["environment"], "prod")
        self.assertEqual(result["expires_in_s"], 900)
        self.assertEqual(result["artifact_handle"], {
            "backend": "s3",
            "bucket": "yoke-prod-artifacts",
            "key": "qa-artifacts/yoke/42/77/home.png",
            "content_type": "image/png",
        })
        parts = urlsplit(result["upload_url"])
        self.assertEqual(parts.scheme, "https")
        self.assertEqual(
            parts.netloc, "yoke-prod-artifacts.s3.us-east-1.amazonaws.com",
        )
        self.assertEqual(parts.path, "/qa-artifacts/yoke/42/77/home.png")
        query = parse_qs(parts.query)
        self.assertEqual(query["X-Amz-Expires"], ["900"])
        self.assertIn("X-Amz-Signature", query)

    def test_target_env_bucket_wins_over_prod(self):
        with test_database() as conn:
            _seed(
                conn, target_env="stage",
                env_buckets={
                    "prod": "yoke-prod-artifacts",
                    "stage": "yoke-stage-artifacts",
                },
            )
            with patch.object(
                qa_artifact_presign, "_capability_credentials",
                return_value=_CREDS,
            ):
                outcome = qa_artifact_presign.handle_qa_artifact_presign(
                    _request({"run_id": 77, "filename": "home.png"}),
                )
        self.assertTrue(outcome.primary_success, outcome.error)
        self.assertEqual(outcome.result_payload["environment"], "stage")
        self.assertEqual(
            outcome.result_payload["artifact_handle"]["bucket"],
            "yoke-stage-artifacts",
        )

    def test_undeclared_target_env_falls_back_to_prod(self):
        with test_database() as conn:
            _seed(
                conn, target_env="local",
                env_buckets={"prod": "yoke-prod-artifacts", "stage": None},
            )
            with patch.object(
                qa_artifact_presign, "_capability_credentials",
                return_value=_CREDS,
            ):
                outcome = qa_artifact_presign.handle_qa_artifact_presign(
                    _request({"run_id": 77, "filename": "home.png"}),
                )
        self.assertTrue(outcome.primary_success, outcome.error)
        self.assertEqual(outcome.result_payload["environment"], "prod")


class TestPresignDenials(unittest.TestCase):
    def test_no_bucket_anywhere_is_typed_s3_not_configured(self):
        with test_database() as conn:
            _seed(conn, env_buckets={"prod": None})
            outcome = qa_artifact_presign.handle_qa_artifact_presign(
                _request({"run_id": 77, "filename": "home.png"}),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "s3_not_configured")
        self.assertIn("artifacts.bucket", outcome.error.message)

    def test_missing_region_is_typed_s3_not_configured(self):
        with test_database() as conn:
            _seed(
                conn,
                env_buckets={"prod": "yoke-prod-artifacts"},
                region=None,
            )
            outcome = qa_artifact_presign.handle_qa_artifact_presign(
                _request({"run_id": 77, "filename": "home.png"}),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "s3_not_configured")
        self.assertIn("region", outcome.error.message)

    def test_missing_capability_secrets_is_typed(self):
        with test_database() as conn:
            _seed(conn, env_buckets={"prod": "yoke-prod-artifacts"})
            with patch.object(
                qa_artifact_presign, "_capability_credentials",
                return_value=None,
            ):
                outcome = qa_artifact_presign.handle_qa_artifact_presign(
                    _request({"run_id": 77, "filename": "home.png"}),
                )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "s3_not_configured")
        self.assertIn("aws-admin", outcome.error.message)

    def test_run_must_belong_to_requirement(self):
        with test_database() as conn:
            _seed(conn, env_buckets={"prod": "b"})
            insert_qa_requirement(
                conn, id=11, item_id=42, qa_kind="browser_smoke",
                qa_phase="verification", blocking_mode="blocking",
                success_policy="{}",
            )
            conn.execute(
                "INSERT INTO qa_runs (id, qa_requirement_id, executor_type, "
                "qa_kind, created_at) VALUES (88, 11, 'browser_substrate', "
                "'browser_smoke', '2026-06-12T00:00:00Z')",
            )
            conn.commit()
            outcome = qa_artifact_presign.handle_qa_artifact_presign(
                _request({"run_id": 88, "filename": "home.png"}),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "target_invalid")

    def test_unsafe_filename_is_payload_invalid(self):
        with test_database() as conn:
            _seed(conn, env_buckets={"prod": "b"})
            with patch.object(
                qa_artifact_presign, "_capability_credentials",
                return_value=_CREDS,
            ):
                outcome = qa_artifact_presign.handle_qa_artifact_presign(
                    _request({"run_id": 77, "filename": "../escape.png"}),
                )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")


if __name__ == "__main__":
    unittest.main()
