"""``environments.settings.servers[0].mac_host``: the Mac that runs the box VM."""

from __future__ import annotations

import pytest

from yoke_core.domain.deploy_environment_settings import deploy_environment_from_settings
from runtime.api.domain.test_deploy_environment_git_branch import (
    _full_capabilities,
    _prod_env,
    _settings,
)


def _resolve(**overrides):
    return deploy_environment_from_settings(
        _settings(environments=[_prod_env(**overrides)], capabilities=_full_capabilities()),
        "prod",
    )


def test_mac_host_is_read_next_to_the_server_key_path() -> None:
    env = _resolve(
        servers=[{"ssh_key_path": "/keys/prod.pem", "mac_host": " testy@testys-mac-mini "}]
    )

    assert env.mac_host == "testy@testys-mac-mini"
    assert env.ssh_key_path == "/keys/prod.pem"
    assert env.ssh_target == "ubuntu@origin.example.com", "other callers keep the origin"


@pytest.mark.parametrize("servers", [None, [], [{}], [{"mac_host": 7}]])
def test_mac_host_is_empty_when_not_declared(servers) -> None:
    overrides = {} if servers is None else {"servers": servers}

    assert _resolve(**overrides).mac_host == ""
