"""Project Structure modules must initialize independently in fresh processes."""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.parametrize("first", [
    "project_structure", "project_structure_write", "project_structure_validation",
    "project_structure_seeds", "project_structure_cli", "workflow_project_defaults",
])
def test_project_structure_import_orders(first):
    modules = [first, "project_structure", "project_structure_write",
               "project_structure_validation", "project_structure_seeds",
               "project_structure_cli", "workflow_project_defaults"]
    code = "\n".join(f"import yoke_core.domain.{module}" for module in modules)
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_project_structure_module_cli():
    result = subprocess.run(
        [sys.executable, "-m", "yoke_core.domain.project_structure", "family-list"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "deploy_defaults" in result.stdout


def test_connection_writer_leaves_transaction_with_caller(test_db):
    from unittest.mock import Mock

    from yoke_core.domain.project_structure import (
        ValidationError, create_project_structure_tables,
    )
    from yoke_core.domain.project_structure_write import apply_patch_on_connection

    create_project_structure_tables(test_db)
    conn = Mock(wraps=test_db)
    op = {"op": "put", "family": "areas", "attachment": "project",
          "entry_key": "transient", "payload": {"description": "pending"}}
    apply_patch_on_connection(conn, "yoke", [op])
    with pytest.raises(ValidationError, match="deployment_flow"):
        apply_patch_on_connection(conn, "yoke", [{
            "op": "put", "family": "deploy_defaults", "attachment": "project",
            "payload": {"wrong_key": "invalid"},
        }])
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()
    assert test_db.execute(
        "SELECT count(*) FROM project_structure WHERE entry_key='transient'"
    ).fetchone()[0] == 1
    test_db.rollback()
    assert test_db.execute(
        "SELECT count(*) FROM project_structure WHERE entry_key='transient'"
    ).fetchone()[0] == 0
