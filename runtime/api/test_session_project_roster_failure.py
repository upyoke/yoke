"""A missing registry never turns into a fabricated session project."""

import pytest

from runtime.api.test_session_project_scope import _make_disposable_db
from yoke_core.domain.session_project_scope import resolve_session_project_scope


@pytest.mark.parametrize("override", [None, ["yoke"], ["1"]])
def test_missing_registry_refuses_instead_of_selecting_project_one(override):
    conn = _make_disposable_db()
    try:
        with pytest.raises(ValueError, match="project_roster_unavailable"):
            resolve_session_project_scope(conn, override=override)
        assert conn.execute("SELECT 1").fetchone()[0] == 1
    finally:
        conn.close()
