"""The machine AWS client consults no shared AWS configuration on disk.

The capability resolver owns credentials, region, and timeouts, so the operator's
``~/.aws`` is not an input. It is an active hazard: on a machine where that
directory is cloud-synced, materialising an evicted file blocked a client build
for minutes, and an ambient profile could answer a lookup the resolver owns.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain import aws_machine_client


def test_shared_config_and_credentials_files_are_detached() -> None:
    detached = aws_machine_client._DETACHED_SESSION_VARS

    for name in ("config_file", "credentials_file"):
        config_key, env_vars, default, _cast = detached[name]
        assert config_key is None
        assert env_vars is None, f"{name} must not be reachable from the environment"
        assert default == os.devnull


def test_an_ambient_profile_cannot_answer_a_resolver_lookup() -> None:
    """An empty config file plus a live ``AWS_PROFILE`` would otherwise raise
    ProfileNotFound, so the profile variable is detached as well."""
    config_key, env_vars, default, _cast = aws_machine_client._DETACHED_SESSION_VARS[
        "profile"
    ]

    assert config_key is None
    assert env_vars is None
    assert default is None


def test_every_detached_variable_is_a_botocore_session_variable() -> None:
    """A typo would be accepted silently and isolate nothing, so the names are
    checked against botocore's own table rather than trusted."""
    from botocore.configprovider import BOTOCORE_DEFAUT_SESSION_VARIABLES

    for name in aws_machine_client._DETACHED_SESSION_VARS:
        assert name in BOTOCORE_DEFAUT_SESSION_VARIABLES


def test_isolated_session_reads_no_shared_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    (home / ".aws").mkdir(parents=True)
    (home / ".aws" / "config").write_text(
        "[default]\nregion = ambient-region\n", encoding="utf-8"
    )
    (home / ".aws" / "credentials").write_text(
        "[default]\naws_access_key_id = ambient-key\n"
        "aws_secret_access_key = ambient-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(home / ".aws" / "config"))
    monkeypatch.setenv(
        "AWS_SHARED_CREDENTIALS_FILE", str(home / ".aws" / "credentials")
    )
    monkeypatch.setenv("AWS_PROFILE", "a-profile-that-does-not-exist")

    session = aws_machine_client._isolated_botocore_session()

    assert session.get_config_variable("config_file") == os.devnull
    assert session.get_config_variable("credentials_file") == os.devnull
    assert session.get_config_variable("profile") is None
    assert session.get_scoped_config() == {}
    assert session.get_config_variable("region") is None


def test_client_is_built_on_the_isolated_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: dict[str, object] = {}
    marker = object()

    class _Session:
        def __init__(self, botocore_session=None) -> None:
            built["botocore_session"] = botocore_session

        def client(self, service_name: str, **kwargs):
            built["service_name"] = service_name
            built["kwargs"] = kwargs
            return marker

    monkeypatch.setattr(
        aws_machine_client, "_isolated_botocore_session", lambda: marker
    )
    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(Session=_Session))

    client = aws_machine_client._boto3_client("sts", region_name="us-east-1")

    assert client is marker
    assert built["botocore_session"] is marker
    assert built["service_name"] == "sts"
    assert built["kwargs"] == {"region_name": "us-east-1"}


def test_resolver_values_still_reach_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Isolation removes ambient inputs, not selected ones."""
    monkeypatch.setattr(
        aws_machine_client.deploy_remote,
        "aws_machine_capability_env",
        lambda _project, _region: {
            "AWS_ACCESS_KEY_ID": "selected-key",
            "AWS_SECRET_ACCESS_KEY": "selected-secret",
            "AWS_SESSION_TOKEN": "selected-token",
            "AWS_REGION": "eu-west-2",
        },
    )
    captured: dict[str, object] = {}

    def _factory(service_name: str, **kwargs):
        captured["service_name"] = service_name
        captured.update(kwargs)
        return object()

    aws_machine_client.machine_aws_client(
        "ec2", "a-project", "us-east-1", client_factory=_factory
    )

    assert captured["service_name"] == "ec2"
    assert captured["aws_access_key_id"] == "selected-key"
    assert captured["aws_secret_access_key"] == "selected-secret"
    assert captured["aws_session_token"] == "selected-token"
    assert captured["region_name"] == "eu-west-2"
