"""Migration applied-everywhere evidence gate — apply-variant scenarios.

The apply variant exercises ``mutation_intent="apply"``: advancing
``implementing → reviewing-implementation`` must fail with the missing
``migration_audit`` row message.  Once an audit row with
``state='completed'`` exists for the listed module on the model's
authoritative DB, the same advance succeeds.

The retire variant lives in :mod:`runtime.api.test_migration_applied_evidence`;
shared fixtures and helpers live in
:mod:`runtime.api.migration_applied_evidence_test_helpers`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from runtime.api.migration_applied_evidence_test_helpers import (
    _advance_status,
    _seed_governed_item,
    regression_db,  # noqa: F401 — re-exported fixture
    tmp_db,  # noqa: F401 — re-exported fixture
)
from runtime.api.test_backlog import _conn


# ---------------------------------------------------------------------------
# AC-60 apply variant
# ---------------------------------------------------------------------------


class TestYok1476ApplyRegression:
    def _profile(self) -> Dict[str, Any]:
        return {
            "state": "declared",
            "model_name": "primary",
            "mutation_intent": "apply",
            "migration_modules": ["new_governed_module"],
            "compatibility_class": "pre_merge_breaking",
            "migration_strategy": "additive_only",
        }

    def _write_module(self, repo_path: Path) -> None:
        target = (
            repo_path / "runtime" / "api" / "domain" / "migrations"
            / "new_governed_module.py"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "MIGRATION = '''\n"
            "ALTER TABLE items ADD COLUMN demo TEXT DEFAULT NULL;\n"
            "'''\n",
            encoding="utf-8",
        )

    def test_advance_refuses_when_audit_row_missing(self, regression_db) -> None:
        self._write_module(regression_db["checkout_path"])
        _seed_governed_item(
            regression_db["db_path"], item_id=1476, profile=self._profile(),
        )
        result = _advance_status(
            regression_db["db_path"], 1476, "reviewing-implementation",
        )
        assert result["success"] is False
        assert result.get("error_code") == "GATE_DB_MUTATION_EVIDENCE"
        assert "no migration_audit row" in result["error"]
        assert "new_governed_module" in result["error"]

    def test_advance_passes_after_completed_audit_row_inserted(
        self, regression_db
    ) -> None:
        self._write_module(regression_db["checkout_path"])
        _seed_governed_item(
            regression_db["db_path"], item_id=1476, profile=self._profile(),
        )
        first = _advance_status(
            regression_db["db_path"], 1476, "reviewing-implementation",
        )
        assert first["success"] is False

        # Insert a "completed" audit row on the connected Postgres authority.
        conn = _conn(regression_db["db_path"])
        try:
            conn.execute(
                "INSERT INTO migration_audit "
                "(migration_name, state, project_id, model_name, started_at) "
                "VALUES (%s, 'completed', 1, 'primary', %s)",
                ("new_governed_module", "2026-04-23T00:00:00Z"),
            )
            conn.commit()
        finally:
            conn.close()

        second = _advance_status(
            regression_db["db_path"], 1476, "reviewing-implementation",
        )
        assert second["success"] is True, second.get("error")
        conn = _conn(regression_db["db_path"])
        try:
            row = conn.execute(
                "SELECT status FROM items WHERE id=%s", (1476,),
            ).fetchone()
        finally:
            conn.close()
        assert row[0] == "reviewing-implementation"
