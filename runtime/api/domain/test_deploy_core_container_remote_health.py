"""Tests for persistent core-container remote health preflights."""

from __future__ import annotations

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
            verify_origin_health(runner, _env(), request_id, lambda _line: None)

        assert "schema_ready=true" in str(exc.value)
        assert "items" in str(exc.value)


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
