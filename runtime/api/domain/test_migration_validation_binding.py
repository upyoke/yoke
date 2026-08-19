"""The validation binding resolves without a DSN passing through an operator."""

from __future__ import annotations

import pytest

from yoke_core.domain import migration_validation_binding as subject


def test_binding_name_appends_the_declared_authority_binding() -> None:
    assert subject.validation_env_var("EXTERNAL_APP_DSN") == (
        "EXTERNAL_APP_DSN_VALIDATION"
    )


def test_written_binding_is_readable_without_an_exported_variable(
    monkeypatch,
) -> None:
    env_var = "EXTERNAL_APP_DSN_VALIDATION"
    monkeypatch.delenv(env_var, raising=False)
    dsn = "host=localhost dbname=external_app_validation"

    path = subject.write_binding(env_var, dsn)

    assert subject.read_binding(env_var) == dsn
    assert path == subject.binding_file(env_var)
    assert path.stat().st_mode & 0o777 == 0o600


def test_exported_variable_wins_over_the_written_binding(monkeypatch) -> None:
    env_var = "EXTERNAL_APP_DSN_VALIDATION"
    subject.write_binding(env_var, "host=localhost dbname=written")
    monkeypatch.setenv(env_var, "host=localhost dbname=exported")

    assert subject.read_binding(env_var) == "host=localhost dbname=exported"


def test_unbound_reads_as_empty_rather_than_raising(monkeypatch) -> None:
    env_var = "NEVER_BOUND_DSN_VALIDATION"
    monkeypatch.delenv(env_var, raising=False)

    assert subject.read_binding(env_var) == ""


def test_binding_file_lives_under_the_machine_secrets_directory() -> None:
    path = subject.binding_file("EXTERNAL_APP_DSN_VALIDATION")

    assert path.parent.name == "secrets"
    assert path.name == "EXTERNAL_APP_DSN_VALIDATION.dsn"


def test_empty_binding_content_is_refused_at_write_time() -> None:
    from yoke_cli.config.secrets import MachineSecretError

    with pytest.raises(MachineSecretError):
        subject.write_binding("EXTERNAL_APP_DSN_VALIDATION", "   ")
