"""Ordinary runner authority remains byte-compatible with installed IaC."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.domain.webapp_pulumi_fakes_test_support import (
    _Recorder,
    _build_fake_pulumi,
)
from runtime.api.tools.runner_fleet_exec_test_support import _runner_values
from yoke_core.tools.runner_fleet_authority_intent import (
    authority_intent_envelope_from_values,
)


@pytest.mark.parametrize("paused", [False, True])
def test_current_authority_against_installed_runner_validator(monkeypatch, paused):
    # The installed validator is immutable source, not a reimplementation.
    import sys

    monkeypatch.setitem(sys.modules, "pulumi", _build_fake_pulumi(_Recorder()))
    path = (
        Path(__file__).resolve().parents[3]
        / "packs/self-hosted-runners/versions/1.3.1/files/infra/webapp_runner_authority_intent.py"
    )
    spec = importlib.util.spec_from_file_location("installed_runner_authority", path)
    installed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installed)
    values = _runner_values()
    values["runner_fleet_lifecycle_writers_paused"] = "true" if paused else "false"
    raw = authority_intent_envelope_from_values(
        project="sample",
        deploy_namespace="sample",
        stack_name="sample-runner-fleet",
        values=values,
        aws_capability="aws-admin",
        aws_region="us-east-1",
    )
    authority = json.loads(raw)["authority"]
    aliases = {
        "github_repo": "repo",
        "github_repo_owner": "repo_owner",
        "github_repo_name": "repo_name",
        "github_installation_id": "installation_id",
        "github_repository_id": "repository_id",
        "github_app_issuer": "app_issuer",
        "github_api_url": "api_url",
        "github_web_url": "web_url",
        "github_private_key_secret_arn": "private_key_secret_arn",
    }
    args = SimpleNamespace(
        **authority, **{key: authority[value] for key, value in aliases.items()}
    )
    monkeypatch.setenv(installed.AUTHORITY_INTENT_ENV, raw)
    if paused:
        with pytest.raises(RuntimeError, match="lifecycle_writers_paused"):
            installed.require_matching_authority_intent(
                args, stack_name="sample-runner-fleet"
            )
    else:
        assert "lifecycle_writers_paused" not in authority
        assert "lifecycle_code_frozen" not in authority
        installed.require_matching_authority_intent(
            args, stack_name="sample-runner-fleet"
        )
