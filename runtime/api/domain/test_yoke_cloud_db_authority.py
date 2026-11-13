"""Unit coverage for Yoke cloud DB authority helpers."""

from __future__ import annotations

import json
import subprocess

import pytest

from yoke_core.domain import yoke_cloud_db_authority
from yoke_core.domain.yoke_cloud_db_authority import (
    CloudAuthorityCommandError,
    PostgresAuthorityLocation,
    PostgresSecret,
    build_libpq_dsn,
    endpoint_and_secret_arn,
    load_secret_string,
    load_stack_outputs,
    redacted_dsn,
)

CAPABILITY_ENV = {"AWS_ACCESS_KEY_ID": "AKIACAPABILITY", "AWS_REGION": "us-east-1"}


def test_secret_json_requires_username_and_password() -> None:
    secret = PostgresSecret.from_json(
        json.dumps({"username": "admin", "password": "pw", "port": "5433"})
    )

    assert secret.username == "admin"
    assert secret.password == "pw"
    assert secret.port == 5433

    with pytest.raises(ValueError, match="password"):
        PostgresSecret.from_json(json.dumps({"username": "admin"}))


def test_endpoint_and_secret_arn_use_declared_output_names() -> None:
    loc = PostgresAuthorityLocation(
        stack="prod",
        database_name="db",
        endpoint_output="endpoint",
        secret_arn_output="secret",
    )

    assert endpoint_and_secret_arn(
        {"endpoint": "host.example", "secret": "arn:secret"}, loc
    ) == ("host.example", "arn:secret")


def test_dsn_quoting_and_redaction() -> None:
    secret = PostgresSecret(username="sun day", password="p w")
    dsn = build_libpq_dsn(
        host="127.0.0.1",
        port=15432,
        database="yoke_prod",
        secret=secret,
    )

    assert "user='sun day'" in dsn
    assert "password='p w'" in dsn
    assert "dbname=yoke_prod" in dsn
    assert redacted_dsn(dsn) == (
        "host=127.0.0.1 port=15432 user=sun day password=<redacted> dbname=yoke_prod"
    )


def test_failing_aws_call_surfaces_redacted_stderr(monkeypatch) -> None:
    seen: dict = {}

    def fake_run(argv, *, env=None, **_kwargs):
        seen["env"] = env
        return subprocess.CompletedProcess(
            argv,
            255,
            stdout="",
            stderr="Could not connect to the endpoint URL; "
            "postgres://admin:pw@db.internal/x password=pw",
        )

    monkeypatch.setattr(yoke_cloud_db_authority.subprocess, "run", fake_run)

    with pytest.raises(CloudAuthorityCommandError) as exc:
        load_secret_string("arn:secret", env=CAPABILITY_ENV)

    assert seen["env"] == CAPABILITY_ENV
    message = str(exc.value)
    assert "aws secretsmanager get-secret-value arn:secret failed" in message
    assert "exit 255: Could not connect to the endpoint URL;" in message
    assert "pw@" not in message and "password=pw" not in message
    assert "yoke aws exec -- secretsmanager describe-secret" in exc.value.recovery


def test_failing_pulumi_call_names_stack_and_cause(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        yoke_cloud_db_authority.subprocess,
        "run",
        lambda argv, **_kw: subprocess.CompletedProcess(
            argv, 255, stdout="", stderr="error: no stack named 'yoke-prod' found"
        ),
    )
    location = PostgresAuthorityLocation(stack="yoke-prod", database_name="db")

    with pytest.raises(CloudAuthorityCommandError) as exc:
        load_stack_outputs(tmp_path, location, env=CAPABILITY_ENV)

    assert exc.value.step == "pulumi stack output --stack yoke-prod"
    assert "no stack named 'yoke-prod' found" in exc.value.detail


@pytest.mark.parametrize(
    ("raised", "detail"),
    [
        (FileNotFoundError("aws"), "`aws` is not installed or not on PATH"),
        (subprocess.TimeoutExpired(["aws"], 120), "no answer within 120s"),
    ],
)
def test_unstartable_or_hung_aws_call_is_a_named_refusal(
    monkeypatch, raised, detail
) -> None:
    def fake_run(argv, **_kwargs):
        raise raised

    monkeypatch.setattr(yoke_cloud_db_authority.subprocess, "run", fake_run)

    with pytest.raises(CloudAuthorityCommandError) as exc:
        load_secret_string("arn:secret", env=CAPABILITY_ENV)

    assert exc.value.detail == detail
