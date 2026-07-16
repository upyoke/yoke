from __future__ import annotations

import os
from pathlib import Path
import stat

import pytest

from runtime.api.domain.test_universe_export import _schema_loaded_universe
from yoke_core.domain import universe_export as ux


def test_export_replaces_existing_archive_with_owner_only_file(tmp_path: Path):
    destination = tmp_path / "graduation.tar"
    destination.write_bytes(b"prior archive")
    destination.chmod(0o644)

    with _schema_loaded_universe() as (_connection, dsn):
        ux.export_universe(dsn=dsn, out=destination)

    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert destination.read_bytes() != b"prior archive"


def test_export_refuses_symlink_destination_without_touching_target(tmp_path: Path):
    protected = tmp_path / "protected.tar"
    protected.write_bytes(b"must remain")
    destination = tmp_path / "graduation.tar"
    destination.symlink_to(protected)

    with _schema_loaded_universe() as (_connection, dsn):
        with pytest.raises(ux.UniverseExportError, match="single-link regular file"):
            ux.export_universe(dsn=dsn, out=destination)

    assert destination.is_symlink()
    assert protected.read_bytes() == b"must remain"


def test_export_refuses_hardlink_destination_without_touching_source(tmp_path: Path):
    protected = tmp_path / "protected.tar"
    protected.write_bytes(b"must remain")
    destination = tmp_path / "graduation.tar"
    os.link(protected, destination)

    with _schema_loaded_universe() as (_connection, dsn):
        with pytest.raises(ux.UniverseExportError, match="single-link regular file"):
            ux.export_universe(dsn=dsn, out=destination)

    assert destination.exists()
    assert protected.read_bytes() == b"must remain"
    assert protected.stat().st_nlink == 2
