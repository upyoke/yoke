"""A declared CI workflow binds only when the gate can reach it.

Registration has an operator present to fix what a refusal names, so it
refuses. The boot-time convergence has none and must not turn one project's
stale declaration into a fleet that will not boot, so it binds the local
runner and reports why. Both readings are pinned here.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import project_checkout_locations
from yoke_core.domain.projects_seed_ci_workflow import (
    CI_WORKFLOW_CAPABILITY_TYPE,
    MERGE_QUEUE_CAPABILITY_TYPE,
)
from yoke_core.domain.qa_command_plan_convergence import (
    converge_registered_command_plans,
)
from yoke_core.domain.qa_command_plan_registration import (
    CI_COMMAND_METHOD_ID,
    LOCAL_COMMAND_METHOD_ID,
    ensure_registered_command_plan,
)


REACHABLE = """
on:
  pull_request:
  merge_group:
  workflow_dispatch:
    inputs:
      yoke_dispatch_id:
        required: false
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: make test
"""

DEPLOY_ONLY = """
on:
  push:
    tags:
      - "v*"
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - run: ./deploy.sh
"""


def _declare_workflow(conn, workflow_file: str) -> None:
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) "
        "VALUES (1, %s, %s)",
        (
            CI_WORKFLOW_CAPABILITY_TYPE,
            json.dumps({"workflow_file": workflow_file}),
        ),
    )
    conn.commit()


def _declare_merge_queue(conn) -> None:
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) "
        "VALUES (1, %s, '{}')",
        (MERGE_QUEUE_CAPABILITY_TYPE,),
    )
    conn.commit()


def _bind_checkout(monkeypatch, tmp_path, workflow_text: str | None):
    """Point the project's checkout at a tree with (or without) a workflow."""
    root = tmp_path / "repo"
    if workflow_text is not None:
        directory = root / ".github" / "workflows"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "ci.yml").write_text(workflow_text, encoding="utf-8")
    else:
        root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        project_checkout_locations,
        "checkout_for_project_id",
        lambda project_id, **kwargs: root,
    )
    return root


def _case_method(conn, scope: str) -> str:
    row = conn.execute(
        "SELECT c.method_id FROM qa_plans p JOIN qa_plan_cases c "
        "ON c.plan_id = p.id WHERE p.project_id=1 AND p.slug=%s",
        (f"registered-command-{scope}",),
    ).fetchone()
    return str(row["method_id"])


def test_a_reachable_workflow_binds_ci_and_reports_it(monkeypatch, tmp_path):
    with test_database() as conn:
        _bind_checkout(monkeypatch, tmp_path, REACHABLE)
        _declare_workflow(conn, "ci.yml")
        result = ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="full",
            command="make test",
        )
        assert result["method_id"] == CI_COMMAND_METHOD_ID
        assert result["ci_workflow_verification"] == "reachable"


def test_registration_refuses_a_workflow_absent_from_the_repository(
    monkeypatch, tmp_path,
):
    with test_database() as conn:
        _bind_checkout(monkeypatch, tmp_path, None)
        _declare_workflow(conn, "ci.yml")
        with pytest.raises(ValueError) as excinfo:
            ensure_registered_command_plan(
                conn, project_id=1, project="yoke", scope="full",
                command="make test",
            )
        assert "does not exist" in str(excinfo.value)


def test_registration_refuses_a_deploy_workflow(monkeypatch, tmp_path):
    with test_database() as conn:
        _bind_checkout(monkeypatch, tmp_path, DEPLOY_ONLY)
        _declare_workflow(conn, "ci.yml")
        with pytest.raises(ValueError) as excinfo:
            ensure_registered_command_plan(
                conn, project_id=1, project="yoke", scope="full",
                command="make test",
            )
        assert "workflow_dispatch" in str(excinfo.value)


def test_an_unreadable_declaration_binds_ci_and_names_what_went_unchecked(
    monkeypatch, tmp_path,
):
    with test_database() as conn:
        monkeypatch.setattr(
            project_checkout_locations,
            "checkout_for_project_id",
            lambda project_id, **kwargs: None,
        )
        _declare_workflow(conn, "ci.yml")
        result = ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="full",
            command="make test",
        )
        assert result["method_id"] == CI_COMMAND_METHOD_ID
        assert result["ci_workflow_verification"] == "checkout_unmapped"


def test_a_project_with_no_declaration_reports_no_workflow_verdict(
    monkeypatch, tmp_path,
):
    with test_database() as conn:
        _bind_checkout(monkeypatch, tmp_path, REACHABLE)
        result = ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="full",
            command="make test",
        )
        assert result["method_id"] == LOCAL_COMMAND_METHOD_ID
        assert result["ci_workflow_verification"] == ""


def test_convergence_binds_local_and_names_the_reason_instead_of_raising(
    monkeypatch, tmp_path,
):
    """A stale declaration must not make the boot converge refuse to boot."""
    with test_database() as conn:
        _bind_checkout(monkeypatch, tmp_path, REACHABLE)
        _declare_workflow(conn, "ci.yml")
        ensure_registered_command_plan(
            conn, project_id=1, project="yoke", scope="full",
            command="make test",
        )
        assert _case_method(conn, "full") == CI_COMMAND_METHOD_ID

        _bind_checkout(monkeypatch, tmp_path / "gone", None)
        converged = converge_registered_command_plans(conn)

        assert _case_method(conn, "full") == LOCAL_COMMAND_METHOD_ID
        entry = next(row for row in converged if row["scope"] == "full")
        assert entry["method_id"] == LOCAL_COMMAND_METHOD_ID
        assert "does not exist" in entry["ci_workflow_unreachable"]
