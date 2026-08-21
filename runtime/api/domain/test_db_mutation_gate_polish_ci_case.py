"""Polish→implemented accepts a CI-routed Command case without a pytest banner."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.db_mutation_gate import (
    check_polishing_implementation_to_implemented_gate,
)
from runtime.api.domain.db_mutation_gate_test_helpers import (
    _seed_project,
    gate_db_context,
)
from runtime.api.fixtures.backlog import (
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)

import pytest


HEAD_SHA = "c" * 40


@pytest.fixture
def gate_db(tmp_path: Path):
    with gate_db_context(tmp_path) as (conn, repo_path):
        yield conn, repo_path


def test_ci_routed_case_passes_without_pytest_banner(gate_db, monkeypatch) -> None:
    conn, repo_path = gate_db
    _seed_project(conn, "yoke", repo_path)
    monkeypatch.setattr(
        "yoke_core.domain.db_mutation_gate_polish.qa_command_plans.get_registered_command",
        lambda project_id, scope, db_path=None: (
            "python3 -m pytest runtime/api/" if scope == "quick" else None
        ),
    )
    insert_item(
        conn, id=5301, project="yoke", status="polishing-implementation",
        test_results="",
    )
    req = insert_qa_requirement(
        conn,
        item_id=5301,
        qa_kind="plan_case",
        method_id="command-ci",
    )
    insert_qa_run(
        conn,
        qa_requirement_id=req["id"],
        verdict="pass",
        raw_result='{"verification_tree":{"head_sha":"' + HEAD_SHA + '"}}',
    )
    outcome = check_polishing_implementation_to_implemented_gate(5301, conn=conn)
    assert outcome.passed, outcome.errors
