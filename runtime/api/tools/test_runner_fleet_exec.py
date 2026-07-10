"""Security contract for runner-fleet child-process authority."""

from __future__ import annotations

from io import StringIO
from types import SimpleNamespace
import subprocess

from yoke_core.tools import runner_fleet_exec
from runtime.api.tools.runner_fleet_exec_test_support import (
    _PRIVATE_KEY,
    _Process,
    _SECRET_ARN,
    _TOKEN,
    _runner_values,
    _write_snapshot,
)


def test_exec_uses_repo_scoped_token_and_redacts_child_streams(
    tmp_path, monkeypatch,
):
    snapshot = _write_snapshot(tmp_path / "stack-config.json")
    value_calls: list[dict[str, object]] = []
    secret_calls: list[dict[str, object]] = []
    mint_calls: list[dict[str, object]] = []
    child_calls: list[dict[str, object]] = []

    def fake_values(settings, *, fallback_repo, enabled):
        value_calls.append({
            "project": settings.project,
            "fallback_repo": fallback_repo,
            "enabled": enabled,
        })
        return _runner_values()

    monkeypatch.setattr(
        runner_fleet_exec, "runner_fleet_values", fake_values,
    )

    def fake_secret_loader(secret_arn, *, region, env):
        secret_calls.append({
            "secret_arn": secret_arn,
            "region": region,
            "env": env,
        })
        return _PRIVATE_KEY

    def fake_token_minter(**kwargs):
        mint_calls.append(kwargs)
        return SimpleNamespace(token=_TOKEN)

    def fake_child_factory(argv, **kwargs):
        child_calls.append({
            "argv": argv,
            **kwargs,
        })
        return _Process(
            returncode=7,
            stdout=(
                "stdout-before token=ghs_repository_",
                "scoped_token stdout-after\n",
                "key=-----BEGIN PRIVATE ",
                "KEY-----\nPRIVATE_KEY_MATERIAL\n",
            ),
            stderr=(
                "stderr-before key-line=PRIVATE_KEY_",
                "MATERIAL token=ghs_repository_scoped_token stderr-after\n",
            ),
        )

    out = StringIO()
    err = StringIO()
    rc = runner_fleet_exec.execute_runner_fleet_command(
        "buzz",
        snapshot,
        ["pulumi", "up", "--yes"],
        aws_env_loader=lambda project, region, *, capability_type: {
            "AWS_REGION": region,
            "GH_TOKEN": "inherited-gh-token",
            "GH_ENTERPRISE_TOKEN": "inherited-enterprise-token",
            "GITHUB_APP_ID": "inherited-app-id",
            "GITHUB_APP_INSTALLATION_ID": "inherited-installation-id",
            "GITHUB_APP_PEM_FILE": "inherited-private-key",
            "GITHUB_BASE_URL": "https://ambient.example/api/v3/",
            "GITHUB_ENTERPRISE_TOKEN": "inherited-github-enterprise-token",
            "GITHUB_ORGANIZATION": "ambient-org",
            "GITHUB_OWNER": "ambient-owner",
            "GITHUB_TOKEN": "inherited-broad-token",
            "RUNNER_FLEET_WEBHOOK_TOKEN": "inherited-webhook-token",
        },
        secret_loader=fake_secret_loader,
        token_minter=fake_token_minter,
        child_factory=fake_child_factory,
        out=out,
        err=err,
    )

    assert rc == 7
    assert value_calls == [{
        "project": "buzz",
        "fallback_repo": "",
        "enabled": True,
    }]
    assert secret_calls == [{
        "secret_arn": _SECRET_ARN,
        "region": "us-east-1",
        "env": {
            "AWS_REGION": "us-east-1",
            "GH_TOKEN": "inherited-gh-token",
            "GH_ENTERPRISE_TOKEN": "inherited-enterprise-token",
            "GITHUB_APP_ID": "inherited-app-id",
            "GITHUB_APP_INSTALLATION_ID": "inherited-installation-id",
            "GITHUB_APP_PEM_FILE": "inherited-private-key",
            "GITHUB_BASE_URL": "https://ambient.example/api/v3/",
            "GITHUB_ENTERPRISE_TOKEN": "inherited-github-enterprise-token",
            "GITHUB_ORGANIZATION": "ambient-org",
            "GITHUB_OWNER": "ambient-owner",
            "GITHUB_TOKEN": "inherited-broad-token",
            "RUNNER_FLEET_WEBHOOK_TOKEN": "inherited-webhook-token",
        },
    }]
    assert mint_calls == [{
        "issuer": "Iv1.runner-fleet",
        "private_key_pem": _PRIVATE_KEY.strip(),
        "installation_id": 123456,
        "api_url": "https://api.github.com",
        "repository_ids": [789012],
        "permissions": {"repository_hooks": "write"},
    }]
    assert len(child_calls) == 1
    child = child_calls[0]
    assert child["argv"] == ["pulumi", "up", "--yes"]
    assert _TOKEN not in child["argv"]
    assert _PRIVATE_KEY not in child["argv"]
    assert child["stdin"] is subprocess.DEVNULL
    assert child["stdout"] is subprocess.PIPE
    assert child["stderr"] is subprocess.PIPE
    assert child["bufsize"] == 0
    assert "text" not in child
    assert "encoding" not in child
    assert "errors" not in child
    child_env = child["env"]
    assert isinstance(child_env, dict)
    assert child_env["RUNNER_FLEET_WEBHOOK_TOKEN"] == _TOKEN
    assert child_env["GITHUB_TOKEN"] == _TOKEN
    assert (
        child_env["RUNNER_FLEET_WEBHOOK_TOKEN"]
        == child_env["GITHUB_TOKEN"]
    )
    assert _PRIVATE_KEY not in child_env.values()
    for name in (
        "GH_TOKEN",
        "GH_ENTERPRISE_TOKEN",
        "GITHUB_APP_ID",
        "GITHUB_APP_INSTALLATION_ID",
        "GITHUB_APP_PEM_FILE",
        "GITHUB_BASE_URL",
        "GITHUB_ENTERPRISE_TOKEN",
        "GITHUB_ORGANIZATION",
        "GITHUB_OWNER",
    ):
        assert name not in child_env
    rendered = out.getvalue() + err.getvalue()
    assert _TOKEN not in rendered
    assert _PRIVATE_KEY.strip() not in rendered
    assert "PRIVATE_KEY_MATERIAL" not in rendered
    assert "[REDACTED]" in rendered
    assert "stdout-before" in out.getvalue()
    assert "stdout-after" in out.getvalue()
    assert "stderr-before" in err.getvalue()
    assert "stderr-after" in err.getvalue()
