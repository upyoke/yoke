"""A declared fleet command gets a minimal environment and redacted output."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from yoke_core.domain.migration_fleet_declared_plan import (
    DeclaredCommandError,
    declared_environment,
    redact_dsn,
    run_declared,
)
from yoke_core.domain.migration_restore_point import RESTORE_POINT_ENV


def test_operator_credentials_never_reach_the_command(monkeypatch) -> None:
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "cloud-secret")
    monkeypatch.setenv("YOKE_PG_DSN", "dbname=prod password=admin-secret")
    monkeypatch.setenv("YOKE_ENV", "prod-db-admin")
    monkeypatch.setenv("UV_CACHE_DIR", "/tmp/uv-cache")
    monkeypatch.setenv(RESTORE_POINT_ENV, "/tmp/copy.dump")

    env = declared_environment("SERVICE_DSN", "dbname=copy")

    assert env["SERVICE_DSN"] == "dbname=copy"
    assert env[RESTORE_POINT_ENV] == "/tmp/copy.dump"
    assert env["UV_CACHE_DIR"] == "/tmp/uv-cache"
    assert "PATH" in env
    for leaked in ("AWS_SECRET_ACCESS_KEY", "YOKE_PG_DSN", "YOKE_ENV"):
        assert leaked not in env


def test_redaction_removes_the_password_in_any_form() -> None:
    dsn = "host=/tmp/sock dbname=copy user=admin password=s3cret"
    text = (
        f"failed: {dsn}; retry postgresql://admin:s3cret@localhost/copy "
        "password='s3cret'"
    )

    redacted = redact_dsn(text, dsn)

    assert "s3cret" not in redacted
    assert "<dsn>" in redacted


def test_failing_command_output_is_redacted(tmp_path: Path) -> None:
    dsn = "dbname=copy password=s3cret"
    code = "import os, sys; sys.stderr.write('bad postgresql://u:s3cret@h/db'); sys.exit(3)"
    with pytest.raises(DeclaredCommandError) as raised:
        run_declared(
            [sys.executable, "-c", code], cwd=tmp_path, env_var="X_DSN", dsn=dsn
        )
    assert "exited 3" in str(raised.value)
    assert "s3cret" not in str(raised.value)
