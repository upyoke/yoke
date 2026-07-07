"""Add-column ambient-init guard.

Invoking the idempotent ``ALTER TABLE ... ADD COLUMN`` site via
:func:`yoke_core.domain.retired_schema_registry.guard_add_column`
against a registered retired column must return ``False`` (i.e. the
caller must skip the ``ADD COLUMN``) and must emit a
:event:`RetiredSchemaResurrectionAttempt` WARN event.  A non-registered
column still returns ``True``.

Shared helpers and the ``_clear_registry_cache`` autouse fixture come from
``add_column_init_guard_test_helpers``.

Guard-subject sqlite: the synthetic sqlite probe DB below exercises the
guarded ``ADD COLUMN`` path against a genuine file-backed connection — the
shape ambient init historically resurrected — not control-plane state.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from yoke_core.domain import retired_schema_registry as rsr
from yoke_core.domain.schema_common import _column_exists

# Re-export shared autouse fixture and the registry helper.
from runtime.api.add_column_init_guard_test_helpers import (  # noqa: F401
    _clear_registry_cache,
    _write_registry,
)


class TestYok1488AmbientInitGuard:
    """Init-guard variant: ADD COLUMN call against a retired column is blocked."""

    def test_guard_blocks_retired_column(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: demo\n"
            "    project: yoke\n"
            "    model: primary\n"
            "    table: projects\n"
            "    column: legacy_retired_col\n",
        )
        rsr.clear_cache()
        emits = {"count": 0}

        def fake_emit(**kwargs):  # noqa: ANN003
            emits["count"] += 1

        monkeypatch.setattr(rsr, "_emit_resurrection_warn", fake_emit)
        allowed = rsr.guard_add_column(
            "yoke", "projects", "legacy_retired_col",
            caller="yoke_core.domain.projects_restart",
            repo_root=tmp_path,
        )
        assert allowed is False
        assert emits["count"] == 1

    def test_guard_allows_unregistered_column(
        self, tmp_path: Path
    ) -> None:
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: demo\n"
            "    project: yoke\n"
            "    model: primary\n"
            "    table: projects\n"
            "    column: legacy_retired_col\n",
        )
        rsr.clear_cache()
        assert rsr.guard_add_column(
            "yoke", "projects", "some_other_col",
            caller="test",
            repo_root=tmp_path,
        ) is True

    def test_end_state_registry_has_no_resurrected_column(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulate ambient init attempting to re-add the retired column.

        Using a synthetic sqlite DB, call the guarded ADD COLUMN path the
        same way ``projects_restart.cmd_init`` does.  After the guard
        fires, verify the column is still absent on the DB through the
        backend-neutral schema helper — the ADD COLUMN must have been
        skipped.
        """
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: demo\n"
            "    project: yoke\n"
            "    model: primary\n"
            "    table: projects\n"
            "    column: legacy_retired_col\n",
        )
        rsr.clear_cache()

        probe_db = tmp_path / "projects.db"
        with sqlite3.connect(str(probe_db)) as conn:
            conn.execute("CREATE TABLE projects (id TEXT PRIMARY KEY)")
            conn.commit()

        monkeypatch.setattr(rsr, "_emit_resurrection_warn", lambda **_k: None)

        # Simulate the idempotent ADD COLUMN path.
        with sqlite3.connect(str(probe_db)) as conn:
            already_present = _column_exists(
                conn, "projects", "legacy_retired_col"
            )
            assert already_present is False
            if rsr.guard_add_column(
                "yoke", "projects", "legacy_retired_col",
                caller="yoke_core.domain.projects_restart",
                repo_root=tmp_path,
            ):
                conn.execute(
                    "ALTER TABLE projects ADD COLUMN legacy_retired_col TEXT"
                )
                conn.commit()

        with sqlite3.connect(str(probe_db)) as conn:
            final_present = _column_exists(conn, "projects", "legacy_retired_col")
        assert final_present is False, (
            "retired column was resurrected despite the guard"
        )
