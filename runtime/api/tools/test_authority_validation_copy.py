"""Tests for the authority-to-validation copy operator helper."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.tools import authority_validation_copy as copy_tool


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
