"""Tests for persistent core-container remote health preflights."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.test_deploy_core_container import _env
from runtime.api.domain.test_deploy_remote import FakeRunner
from yoke_core.domain.deploy_core_container_remote import (
    RemoteConvergenceError,
    verify_origin_health,
    verify_runtime_database_secret_access,
)
from yoke_core.domain.deploy_remote import CommandResult


class TestOriginHealthGate:
    def test_requires_schema_ready_payload(self):
        request_id = "rid-123"
        runner = FakeRunner(
            [
                CommandResult(
                    0,
                    "HTTP/1.1 200 OK\n"
                    f"x-request-id: {request_id}\n\n"
                    '{"status":"ok","schema_ready":false,'
                    '"schema_missing_tables":["items"]}',
                    "",
                )
            ]
        )

        with pytest.raises(RemoteConvergenceError) as exc:
            verify_origin_health(
                runner, _env(), request_id, "abc123def456", lambda _line: None
            )

        assert "schema_ready=true" in str(exc.value)
        assert "items" in str(exc.value)

    @pytest.mark.parametrize(
        ("migration_fields", "expected", "detail"),
        [
            (
                {
                    "migrations_current": False,
                    "pending_migrations": ["0004_backfill_serving_floors"],
                },
                "migrations_current=true",
                "0004_backfill_serving_floors",
            ),
            (
                {
                    "migrations_current": True,
                    "can_serve_this_database": False,
                    "stranded_by_migrations": ["0001 requires launch.181"],
                },
                "can_serve_this_database=false",
                "0001 requires launch.181",
            ),
            (
                {
                    "migrations_current": True,
                    "can_serve_this_database": True,
                    "migration_content_matches": False,
                    "migration_content_mismatches": [
                        "0005_inbox_notification_projection: digest mismatch"
                    ],
                },
                "migration_content_matches=true",
                "0005_inbox_notification_projection",
            ),
            (
                {
                    "migrations_current": True,
                    "can_serve_this_database": True,
                    "migration_content_matches": True,
                    "migration_content_evidence_ready": False,
                },
                "migration_content_evidence_ready=true",
                "migration_content_evidence_ready",
            ),
            (
                {
                    "migrations_current": True,
                    "can_serve_this_database": True,
                    "migration_content_matches": True,
                    "migration_content_evidence_ready": True,
                    "migration_content_adoption_required": ["0001_existing"],
                },
                "migration_content_adoption_required",
                "0001_existing",
            ),
        ],
    )
    def test_rejects_explicit_migration_refusal(
        self, migration_fields, expected, detail
    ):
        request_id = "rid-migrations"
        payload = {
            "status": "ok",
            "schema_ready": True,
            "build": "abc123def456",
            "engine_version": "0.1.1+launch.200",
            **migration_fields,
        }
        runner = FakeRunner(
            [
                CommandResult(
                    0,
                    "HTTP/1.1 200 OK\n"
                    f"x-request-id: {request_id}\n\n" + json.dumps(payload),
                    "",
                )
            ]
        )

        with pytest.raises(RemoteConvergenceError) as exc:
            verify_origin_health(
                runner, _env(), request_id, "abc123def456", lambda _line: None
            )

        assert expected in str(exc.value)
        assert detail in str(exc.value)

    @pytest.mark.parametrize(
        "payload",
        [
            {
                "status": "ok",
                "schema_ready": True,
                "build": "stale1234567",
                "engine_version": "0.1.1+launch.25",
            },
            {
                "status": "ok",
                "schema_ready": True,
                "build": "abc123def456",
                "engine_version": "",
            },
        ],
    )
    def test_requires_exact_build_and_advertised_engine_version(self, payload):
        request_id = "rid-release"
        runner = FakeRunner(
            [
                CommandResult(
                    0,
                    "HTTP/1.1 200 OK\n"
                    f"x-request-id: {request_id}\n\n" + json.dumps(payload),
                    "",
                )
            ]
        )

        with pytest.raises(RemoteConvergenceError, match="release identity mismatch"):
            verify_origin_health(
                runner, _env(), request_id, "abc123def456", lambda _line: None
            )


class TestRuntimeDatabaseSecretPreflight:
    def test_rejects_runtime_without_database_secret_access(self):
        runner = FakeRunner([CommandResult(254, "", "AccessDeniedException")])

        with pytest.raises(RemoteConvergenceError) as exc:
            verify_runtime_database_secret_access(
                runner,
                _env(),
                lambda _line: None,
            )

        assert "database secret access preflight" in str(exc.value)
        assert "secretsmanager:GetSecretValue" in str(exc.value)
