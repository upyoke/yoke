"""Environment-origin GitHub App key policy scope."""

from __future__ import annotations

import json

from runtime.api.domain.test_webapp_environment_stack import _environment_stack


_SECRET_ARN = (
    "arn:aws:secretsmanager:us-east-1:123456789012:"
    "secret:yoke/prod/github-app-private-key-AbCdEf"
)


def test_origin_role_reads_only_its_environment_app_key(monkeypatch):
    recorder, _stack = _environment_stack(
        monkeypatch,
        github_app_private_key_secret_arn=_SECRET_ARN,
    )
    statements = json.loads(
        recorder.single("originRolePolicy").kwargs["policy"]
    )["Statement"]
    app_key = next(
        statement for statement in statements
        if statement.get("Sid") == "ReadEnvironmentGitHubAppPrivateKey"
    )
    assert app_key["Resource"] == _SECRET_ARN
    assert app_key["Action"] == [
        "secretsmanager:DescribeSecret",
        "secretsmanager:GetSecretValue",
    ]


def test_origin_role_decrypts_only_declared_app_key_kms_key(monkeypatch):
    key_arn = (
        "arn:aws:kms:us-east-1:123456789012:key/"
        "11111111-2222-3333-4444-555555555555"
    )
    recorder, _stack = _environment_stack(
        monkeypatch,
        github_app_private_key_secret_arn=_SECRET_ARN,
        github_app_kms_key_arn=key_arn,
    )
    statements = json.loads(
        recorder.single("originRolePolicy").kwargs["policy"]
    )["Statement"]
    decrypt = next(
        statement for statement in statements
        if statement.get("Sid") == "DecryptEnvironmentGitHubAppPrivateKey"
    )
    assert decrypt["Resource"] == key_arn
    assert decrypt["Action"] == ["kms:Decrypt", "kms:DescribeKey"]
