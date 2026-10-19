"""Setup reuses the connection a person just approved for the same server."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_cli.config import writer
from yoke_cli.config.onboard_wizard import WizardDefaults
from yoke_cli.config.onboard_wizard_stored_connection import (
    StoredConnectionHydration,
)

SERVER = "http://127.0.0.1:19121"


def _shell(config_path: str) -> SimpleNamespace:
    shell = SimpleNamespace(
        result=SimpleNamespace(
            config_path=config_path,
            env_name="prod",
            api_url=SERVER,
            token=None,
            token_file=None,
            token_source_kind="prompt",
        ),
        _stored_yoke_token_available=False,
    )
    return shell


@pytest.fixture
def machine_home(tmp_path, monkeypatch):
    home = tmp_path / "machine"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    return home


def _save(machine_home, env: str, api_url: str) -> str:
    token = machine_home / f"{env}.token-source"
    token.write_text("opaque-test-token\n", encoding="utf-8")
    token.chmod(0o600)
    writer.set_connection(
        env,
        transport="https",
        api_url=api_url,
        token_file=str(token),
        prod=False,
        activate=True,
    )
    return str(machine_home / "config.json")


def test_defaulted_env_reuses_the_active_connection_for_this_server(machine_home):
    # Invite redemption saves the teammate's connection under the org name.
    config = _save(machine_home, "default", SERVER)
    shell = _shell(config)
    StoredConnectionHydration._hydrate_stored_yoke_connection(
        shell, WizardDefaults(config_path=config, env_name="prod", api_url=SERVER)
    )
    assert shell._stored_yoke_token_available is True
    assert shell.result.env_name == "default"
    assert shell.result.token_file


def test_another_server_is_never_reused(machine_home):
    config = _save(machine_home, "default", "http://127.0.0.1:19122")
    shell = _shell(config)
    StoredConnectionHydration._hydrate_stored_yoke_connection(
        shell, WizardDefaults(config_path=config, env_name="prod", api_url=SERVER)
    )
    assert shell._stored_yoke_token_available is False
    assert shell.result.token_file is None


def test_a_named_env_that_is_missing_reuses_nothing(machine_home):
    config = _save(machine_home, "default", SERVER)
    shell = _shell(config)
    StoredConnectionHydration._hydrate_stored_yoke_connection(
        shell, WizardDefaults(config_path=config, env_name="team", api_url=SERVER)
    )
    assert shell._stored_yoke_token_available is False
