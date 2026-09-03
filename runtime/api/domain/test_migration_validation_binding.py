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


def test_recorded_bindings_name_databases_without_returning_a_dsn(
    monkeypatch,
) -> None:
    env_var = "EXTERNAL_APP_DSN_VALIDATION"
    monkeypatch.delenv(env_var, raising=False)
    subject.write_binding(env_var, "host=localhost dbname=external_app_validation")

    recorded = [b for b in subject.recorded_bindings() if b.env_var == env_var]

    assert [b.database for b in recorded] == ["external_app_validation"]
    assert all("host=" not in b.source for b in recorded)


def test_an_export_pointing_elsewhere_does_not_hide_the_written_binding(
    monkeypatch,
) -> None:
    # read_binding lets the export win for the run it is steering, but the
    # database the file names is still sitting on its cluster. A fleet that
    # saw only the export would rehearse the other one as a tenant.
    env_var = "EXTERNAL_APP_DSN_VALIDATION"
    subject.write_binding(env_var, "host=localhost dbname=written_validation")
    monkeypatch.setenv(env_var, "host=localhost dbname=exported_validation")

    databases = {b.database for b in subject.recorded_bindings()}

    assert {"written_validation", "exported_validation"} <= databases


def test_an_unreadable_binding_is_reported_rather_than_dropped(
    monkeypatch,
) -> None:
    env_var = "EXTERNAL_APP_DSN_VALIDATION"
    monkeypatch.delenv(env_var, raising=False)
    subject.write_binding(env_var, "not a dsn at all")

    recorded = [b for b in subject.recorded_bindings() if b.env_var == env_var]

    assert [b.database for b in recorded] == [""]


def test_a_superseded_binding_file_is_not_a_binding(monkeypatch) -> None:
    # `.dsn.stale` is how a rotated binding is set aside. Reading it back as
    # live would exclude a database nothing rehearses any more.
    env_var = "EXTERNAL_APP_DSN_VALIDATION"
    monkeypatch.delenv(env_var, raising=False)
    live = subject.write_binding(env_var, "host=localhost dbname=live_validation")
    live.with_name(live.name + ".stale").write_text(
        "host=localhost dbname=retired_validation\n", encoding="utf-8"
    )

    databases = {b.database for b in subject.recorded_bindings()}

    assert "live_validation" in databases
    assert "retired_validation" not in databases


def test_the_control_plane_binding_name_is_derived_not_spelled() -> None:
    from yoke_contracts.control_plane_locality import PG_DSN_ENV

    assert subject.YOKE_VALIDATION_DSN_ENV == subject.validation_env_var(PG_DSN_ENV)
