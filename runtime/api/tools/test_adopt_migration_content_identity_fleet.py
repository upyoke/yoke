"""Fleet discovery coverage for installed migration-content adoption."""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from types import TracebackType
from typing import Any

import psycopg
import pytest

from yoke_core.domain import db_backend
from yoke_core.tools import adopt_migration_content_identity as tool

from runtime.api.tools.test_adopt_migration_content_identity import (
    _argv,
    _artifact,
    _legacy_connection,
    _mock_admin_authority,
    _mock_github_attestations,
)


class _CatalogCursor(AbstractContextManager["_CatalogCursor"]):
    def __init__(self) -> None:
        self.query: tuple[str, tuple[str, ...]] | None = None

    def __enter__(self) -> "_CatalogCursor":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def execute(self, statement: str, parameters: tuple[str, ...]) -> None:
        self.query = (statement, parameters)

    def fetchall(self) -> list[tuple[str]]:
        return [("yoke_platform",), ("yoke_alpha",), ("yoke_beta",)]


class _CatalogConnection(AbstractContextManager["_CatalogConnection"]):
    def __init__(self, cursor: _CatalogCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "_CatalogConnection":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def cursor(self) -> _CatalogCursor:
        return self._cursor


def test_omitted_database_operands_discover_fleet_from_selected_admin_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheel, manifest, evidence, digest = _artifact(tmp_path)
    _mock_github_attestations(monkeypatch)
    _mock_admin_authority(monkeypatch)
    cursor = _CatalogCursor()
    discovered_dsns: list[str] = []
    selected_dsns: list[str] = []

    def connect_catalog(dsn: str, **_kwargs: Any) -> _CatalogConnection:
        discovered_dsns.append(dsn)
        return _CatalogConnection(cursor)

    def connect_tenant(dsn: str):
        selected_dsns.append(dsn)
        return _legacy_connection()

    monkeypatch.setattr(psycopg, "connect", connect_catalog)
    monkeypatch.setattr(db_backend, "connect_psycopg", connect_tenant)

    assert (
        tool.main(
            _argv(
                wheel,
                manifest,
                evidence,
                digest,
                mode="prepare",
                databases=(),
            )
        )
        == 0
    )

    from psycopg import conninfo

    parsed = [conninfo.conninfo_to_dict(dsn) for dsn in discovered_dsns + selected_dsns]
    assert [dsn["dbname"] for dsn in parsed] == [
        "yoke_platform",
        "yoke_alpha",
        "yoke_beta",
    ]
    assert {dsn["host"] for dsn in parsed} == {"selected.example"}
    assert {dsn["user"] for dsn in parsed} == {"admin"}
    assert cursor.query is not None
    assert cursor.query[1] == ("yoke_%",)
