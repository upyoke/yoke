from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import universe_portability as portability


def test_dump_resolves_client_before_creating_private_output(
    monkeypatch,
    tmp_path: Path,
):
    prepared = []
    monkeypatch.setattr(portability, "_postgres_executable", lambda _name: "pg_dump")
    monkeypatch.setattr(
        portability,
        "postgres_client_env",
        lambda _dsn: (_ for _ in ()).throw(ValueError("unsupported DSN")),
    )
    monkeypatch.setattr(
        portability.universe_archive_output,
        "prepare_private_archive_output",
        lambda destination: prepared.append(destination),
    )

    with pytest.raises(ValueError, match="unsupported DSN"):
        portability.dump_universe("invalid", tmp_path / "export.dump")

    assert prepared == []
