"""Tests for yoke_core.domain.db_helpers retired DB path guard."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import resolve_db_path


@pytest.mark.skipif(
    not db_backend.is_postgres(),
    reason="Postgres-only guard contract.",
)
def test_resolve_db_path_guarded_under_postgres(tmp_path: Path) -> None:
    db_file = tmp_path / "custom.db"
    with mock.patch.dict(os.environ, {"YOKE_DB": str(db_file)}, clear=False):
        with pytest.raises(RuntimeError, match="Postgres authority"):
            resolve_db_path()
