"""Project-local QA method authoring tests."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_method_management import (
    QaMethodError,
    register_project_method,
)


def test_project_method_uses_registered_executor_contract() -> None:
    with test_database() as conn:
        result = register_project_method(
            conn,
            project="yoke",
            slug="checkout-lint",
            name="Checkout lint",
            description="Run the project's deterministic checkout lint.",
            executor_id="worktree_run",
            verdict_path="automatic",
            verdict_contract="exit 0 = pass",
            evidence_contract="captured command output",
        )
        row = conn.execute(
            "SELECT source_kind, project_id, executor_id, display_icon, "
            "display_group, config_contract_id, proof_kind, executor_gloss "
            "FROM qa_methods WHERE id=%s",
            (result["id"],),
        ).fetchone()

    assert result["id"] == "project-yoke-checkout-lint"
    assert (row["source_kind"], row["project_id"], row["executor_id"]) == (
        "project",
        1,
        "worktree_run",
    )
    assert {
        "display_icon": row["display_icon"],
        "display_group": row["display_group"],
        "config_contract_id": row["config_contract_id"],
        "proof_kind": row["proof_kind"],
        "executor_gloss": row["executor_gloss"],
    } == {
        "display_icon": "⌥",
        "display_group": "Command",
        "config_contract_id": "command",
        "proof_kind": "command",
        "executor_gloss": "runs the case's command in the item worktree",
    }


def test_project_method_rejects_unregistered_executor() -> None:
    with test_database() as conn:
        with pytest.raises(QaMethodError, match="not registered"):
            register_project_method(
                conn,
                project="yoke",
                slug="arbitrary-script",
                name="Arbitrary script",
                description="An unsupported executor.",
                executor_id="shell_anything",
                verdict_path="automatic",
                verdict_contract="unknown",
                evidence_contract="unknown",
            )
