"""Tests for the authority-to-validation copy operator helper."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.tools import authority_validation_copy as copy_tool
from yoke_core.domain.scratch_database_authority import ScratchDatabaseRefused
from yoke_core.domain.migration_validation_binding import read_binding


def test_refuses_the_authoritative_database_as_validation(monkeypatch) -> None:
    monkeypatch.setattr(
        copy_tool.db_backend,
        "resolve_pg_dsn",
        lambda: "host=authority password=secret dbname=yoke",
    )
    monkeypatch.setattr(
        copy_tool,
        "_database_identity",
        lambda _dsn: ("yoke", "10.0.0.1", "5432"),
    )

    with pytest.raises(
        copy_tool.ValidationCopyError,
        match="resolves to the authoritative database",
    ):
        copy_tool.copy_authority_to_validation(
            "host=authority password=other dbname=yoke"
        )


def test_copies_with_no_owner_or_privilege_restore(monkeypatch) -> None:
    authority_dsn = "host=authority password=top-secret dbname=yoke"
    validation_dsn = "host=validation user=test dbname=yoke_validation"
    monkeypatch.setattr(
        copy_tool.db_backend,
        "resolve_pg_dsn",
        lambda: authority_dsn,
    )
    monkeypatch.setattr(
        copy_tool,
        "_database_identity",
        lambda dsn: (
            ("yoke", "10.0.0.1", "5432")
            if dsn == authority_dsn
            else ("yoke_validation", "local-socket", "5432")
        ),
    )
    resets: list[str] = []
    monkeypatch.setattr(copy_tool, "_reset_validation_schema", resets.append)
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(argv, **_kwargs):
        calls.append((list(argv), dict(_kwargs["env"])))
        if argv[0] == "pg_dump":
            archive = Path(argv[argv.index("--file") + 1])
            archive.write_bytes(b"archive")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(copy_tool.subprocess, "run", fake_run)

    result = copy_tool.copy_authority_to_validation(validation_dsn)

    assert result == ("yoke", "yoke_validation")
    dump_argv, dump_env = calls[0]
    restore_argv, restore_env = calls[1]
    assert dump_argv[0] == "pg_dump"
    assert restore_argv[0] == "pg_restore"
    assert "--no-owner" in dump_argv
    assert "--no-privileges" in dump_argv
    assert "--clean" not in restore_argv
    assert "--if-exists" not in restore_argv
    assert "--exit-on-error" in restore_argv
    assert authority_dsn not in dump_argv
    assert validation_dsn not in restore_argv
    assert "top-secret" not in " ".join(dump_argv)
    assert dump_env["PGPASSWORD"] == "top-secret"
    assert restore_env.get("PGPASSWORD") is None
    assert resets == [validation_dsn]


def test_derives_a_disposable_target_when_nothing_is_bound(monkeypatch) -> None:
    monkeypatch.delenv(copy_tool.VALIDATION_DSN_ENV, raising=False)

    resolved, derived = copy_tool.resolve_validation_dsn(
        "host=localhost dbname=yoke password=top-secret"
    )

    assert derived is True
    assert "dbname=yoke_validation" in resolved
    # Same cluster and credentials, so no DSN has to be authored by hand.
    assert "host=localhost" in resolved
    assert "password=top-secret" in resolved


def test_a_bound_target_wins_over_deriving_one(monkeypatch) -> None:
    bound = "host=elsewhere dbname=chosen_scratch"
    monkeypatch.setenv(copy_tool.VALIDATION_DSN_ENV, bound)

    assert copy_tool.resolve_validation_dsn("host=localhost dbname=yoke") == (
        bound,
        False,
    )


def test_an_authority_without_a_database_name_cannot_derive(monkeypatch) -> None:
    monkeypatch.delenv(copy_tool.VALIDATION_DSN_ENV, raising=False)

    with pytest.raises(copy_tool.ValidationCopyError, match="names no database"):
        copy_tool.resolve_validation_dsn("host=localhost")


def test_provisioning_creates_hydrates_and_binds_without_printing_a_dsn(
    monkeypatch, capsys
) -> None:
    authority_dsn = "host=localhost dbname=yoke password=top-secret"
    monkeypatch.delenv(copy_tool.VALIDATION_DSN_ENV, raising=False)
    monkeypatch.setattr(copy_tool.db_backend, "resolve_pg_dsn", lambda: authority_dsn)
    created: list[str] = []
    monkeypatch.setattr(copy_tool, "create_database_if_absent", created.append)
    monkeypatch.setattr(
        copy_tool,
        "_copy",
        lambda _authority, _validation: ("yoke", "yoke_validation"),
    )

    assert copy_tool.main([]) == 0

    reported = capsys.readouterr().out
    assert "authority=yoke validation=yoke_validation" in reported
    assert "top-secret" not in reported
    assert "dbname=" not in reported
    assert len(created) == 1
    # The binding rehearsal reads is what provisioning leaves behind.
    assert read_binding(copy_tool.VALIDATION_DSN_ENV) == created[0]


def test_provisioning_does_not_create_a_database_an_operator_bound(
    monkeypatch,
) -> None:
    bound = "host=elsewhere dbname=chosen_scratch"
    monkeypatch.setenv(copy_tool.VALIDATION_DSN_ENV, bound)
    monkeypatch.setattr(
        copy_tool.db_backend, "resolve_pg_dsn", lambda: "host=localhost dbname=yoke"
    )
    monkeypatch.setattr(
        copy_tool,
        "create_database_if_absent",
        lambda _dsn: pytest.fail("created a database the operator already chose"),
    )
    monkeypatch.setattr(copy_tool, "_copy", lambda _a, _v: ("yoke", "chosen_scratch"))

    assert copy_tool.main([]) == 0


def test_derived_validation_creator_names_its_exact_target_to_the_guard(
    monkeypatch,
) -> None:
    validation_dsn = "host=127.0.0.1 port=6547 dbname=yoke_validation"
    observed = {}

    def refuse(name: str, *, target_dsn: str) -> None:
        observed.update(name=name, target_dsn=target_dsn)
        raise ScratchDatabaseRefused("administered target")

    monkeypatch.setattr(
        copy_tool,
        "refuse_scratch_database_on_administered_cluster",
        refuse,
    )
    monkeypatch.setattr(
        copy_tool.psycopg,
        "connect",
        lambda *_args, **_kwargs: pytest.fail("connected before target refusal"),
    )

    with pytest.raises(ScratchDatabaseRefused):
        copy_tool.create_database_if_absent(validation_dsn)

    assert observed == {
        "name": "yoke_validation",
        "target_dsn": validation_dsn,
    }
