"""A new universe's first admin is named for the installer, never a placeholder."""

from __future__ import annotations

import pytest

from yoke_cli.self_host import bundle
from yoke_contracts.first_admin_name import (
    ADMIN_NAME_ENV,
    ADMIN_NAME_MISSING,
    AdminNameError,
    validate_admin_name,
)
from yoke_core.api import server_entrypoint


def test_validator_strips_and_keeps_a_real_name():
    assert validate_admin_name("  Ada Lovelace ") == "Ada Lovelace"
    assert validate_admin_name("José Ñúñez-O’Brien") == "José Ñúñez-O’Brien"


@pytest.mark.parametrize(
    "value", [None, "", "   ", "a$b", "Ada # x", 'say "hi"', "a\nb"]
)
def test_validator_refuses_what_the_bundle_cannot_carry(value):
    with pytest.raises(AdminNameError):
        validate_admin_name(value)


def test_server_birth_refuses_without_a_name_and_names_the_recovery(monkeypatch):
    monkeypatch.delenv(ADMIN_NAME_ENV, raising=False)
    with pytest.raises(RuntimeError) as refused:
        server_entrypoint.first_admin_name()
    message = str(refused.value)
    assert message.startswith(f"{ADMIN_NAME_MISSING}:")
    assert "yoke setup" in message
    assert "--protect-existing --start" in message


def test_server_birth_reads_the_bundle_name(monkeypatch):
    monkeypatch.setenv(ADMIN_NAME_ENV, " Ada Lovelace ")
    assert server_entrypoint.first_admin_name() == "Ada Lovelace"


def test_bundle_carries_the_name_into_env_and_compose(tmp_path):
    report = bundle.write_bundle(
        directory=str(tmp_path / "server"),
        image="candidate:immutable",
        admin_name="Ada Lovelace",
    )
    env = (tmp_path / "server" / bundle.ENV_FILE_NAME).read_text(encoding="utf-8")
    assert f"{ADMIN_NAME_ENV}=Ada Lovelace\n" in env
    assert report["admin_name"] == "Ada Lovelace"
    assert f"{ADMIN_NAME_ENV}: ${{{ADMIN_NAME_ENV}:-}}" in bundle._compose_text()


def test_bundle_refuses_a_new_universe_without_a_name(tmp_path):
    target = tmp_path / "server"
    with pytest.raises(bundle.SelfHostBundleError, match="--admin-name"):
        bundle.write_bundle(directory=str(target), image="candidate:immutable")
    assert not (target / bundle.ENV_FILE_NAME).exists()
