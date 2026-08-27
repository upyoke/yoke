"""The retired file-path helper must not come back via PYTHONPATH."""

from __future__ import annotations

from yoke_core.domain import db_helpers


def _retired_path_helper() -> str:
    return "resolve" + "_db_path"


def test_db_helpers_has_no_retired_path_helper() -> None:
    assert not hasattr(db_helpers, _retired_path_helper())
