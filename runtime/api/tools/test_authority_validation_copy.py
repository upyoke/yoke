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
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        if argv[0] == "pg_dump":
            archive = Path(argv[argv.index("--file") + 1])
            archive.write_bytes(b"archive")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(copy_tool.subprocess, "run", fake_run)

    result = copy_tool.copy_authority_to_validation(validation_dsn)

    assert result == ("yoke", "yoke_validation")
    assert calls[0][0] == "pg_dump"
    assert calls[1][0] == "pg_restore"
    assert "--no-owner" in calls[0]
    assert "--no-privileges" in calls[0]
    assert "--clean" in calls[1]
    assert "--if-exists" in calls[1]
    assert "--exit-on-error" in calls[1]
    assert validation_dsn in calls[1]

