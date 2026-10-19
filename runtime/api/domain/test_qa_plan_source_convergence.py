"""Boot moves source-bound plans forward to the cases the serving build authors."""

import logging

import pytest

from runtime.api.domain.test_installer_campaign_plan_sync import (
    source_checkout as source_checkout,
)
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import create_smoke_plan
from yoke_core.domain import qa_plan_source_revision as source_binding
from yoke_core.domain import schema_init
from yoke_core.domain.deployment_run_carried_work_source import LocalCheckoutSource
from yoke_core.domain.qa_plan_source_convergence import converge_source_bound_plans
from yoke_core.tools import installer_campaign_plan

SLUG = "installer-campaign"


def _authored(case_key="command-smoke", instructions="run the frozen smoke command"):
    return {
        "case_key": case_key,
        "position": 1,
        "method_id": "command",
        "instructions": instructions,
        "expected_outcome": "the command passes",
        "method_config": {"command": "true"},
    }


@pytest.fixture
def bound_plan(test_db, source_checkout, monkeypatch):
    """A source-bound plan, a newer merged build, and that build's cases."""
    root, git = source_checkout
    old = git(root, "rev-parse", "HEAD").stdout.strip()
    pid = create_smoke_plan(test_db, project="yoke", slug=SLUG)
    test_db.execute("UPDATE projects SET default_branch='stable' WHERE id=1")
    test_db.execute("UPDATE qa_plans SET source_revision=%s WHERE id=%s", (old, pid))
    test_db.commit()
    (root / "cases.json").write_text('["new behavior"]\n')
    assert git(root, "commit", "-am", "Change authored cases").returncode == 0
    assert git(root, "push", "origin", "stable").returncode == 0
    new = git(root, "rev-parse", "HEAD").stdout.strip()
    monkeypatch.setattr(
        source_binding,
        "open_carried_work_source",
        lambda conn, project_id: LocalCheckoutSource(str(root)),
    )
    build_cases = {"cases": [_authored(instructions="run the new smoke command")]}

    def compare(plan):
        installed = [c["instructions"] for c in plan["cases"]]
        generated = [c["instructions"] for c in build_cases["cases"]]
        differences = [] if installed == generated else [{"case_key": "command-smoke"}]
        return build_cases["cases"], {
            "matches_source": not differences,
            "differences": differences,
        }

    monkeypatch.setattr(installer_campaign_plan, "compare_plan", compare)
    return pid, old, new, build_cases


def _plan_state(test_db, pid):
    revision = test_db.execute(
        "SELECT source_revision FROM qa_plans WHERE id=%s", (pid,)
    ).fetchone()[0]
    instructions = test_db.execute(
        "SELECT instructions FROM qa_plan_cases WHERE plan_id=%s", (pid,)
    ).fetchone()[0]
    return revision, instructions


def test_newer_build_replaces_drifted_cases_and_records_its_source(test_db, bound_plan):
    pid, old, new, _ = bound_plan
    outcomes = converge_source_bound_plans(test_db, build_sha=new)
    assert [o["result"] for o in outcomes] == ["converged"]
    assert _plan_state(test_db, pid) == (new, "run the new smoke command")


def test_older_build_never_moves_a_plan_backwards(test_db, bound_plan, caplog):
    pid, old, new, build_cases = bound_plan
    converge_source_bound_plans(test_db, build_sha=new)
    build_cases["cases"] = [_authored()]
    with caplog.at_level(logging.INFO):
        outcomes = converge_source_bound_plans(test_db, build_sha=old)
    assert outcomes[0]["result"] == "skipped"
    assert "qa_plan_source_revision_regression" in outcomes[0]["reason"]
    assert "qa_plan_source_newer_kept" in caplog.text
    assert _plan_state(test_db, pid) == (new, "run the new smoke command")


def test_matching_cases_are_left_untouched(test_db, bound_plan):
    pid, old, new, build_cases = bound_plan
    build_cases["cases"] = [_authored()]
    outcomes = converge_source_bound_plans(test_db, build_sha=new)
    assert [o["result"] for o in outcomes] == ["current"]
    assert _plan_state(test_db, pid) == (old, "run the frozen smoke command")


def test_unmerged_build_keeps_cases_and_logs_the_recovery(
    test_db, bound_plan, source_checkout, caplog
):
    pid, old, new, _ = bound_plan
    root, git = source_checkout
    assert git(root, "checkout", "-b", "unmerged").returncode == 0
    (root / "cases.json").write_text('["unmerged"]\n')
    assert git(root, "commit", "-am", "Unmerged cases").returncode == 0
    unmerged = git(root, "rev-parse", "HEAD").stdout.strip()
    with caplog.at_level(logging.WARNING):
        outcomes = converge_source_bound_plans(test_db, build_sha=unmerged)
    assert outcomes[0]["result"] == "skipped"
    assert "qa_plan_source_unmerged_or_unverified" in outcomes[0]["reason"]
    assert "qa_plan_source_convergence_failed" in caplog.text
    assert "yoke qa plan-cases sync" in caplog.text
    assert _plan_state(test_db, pid) == (old, "run the frozen smoke command")


def test_unbound_retired_and_unauthored_plans_are_not_examined(test_db, bound_plan):
    pid, old, new, _ = bound_plan
    other = create_smoke_plan(test_db, project="yoke", slug="team-smoke")
    test_db.execute("UPDATE qa_plans SET source_revision=%s WHERE id=%s", (old, other))
    test_db.execute("UPDATE qa_plans SET retired_at=now() WHERE id=%s", (pid,))
    test_db.commit()
    assert converge_source_bound_plans(test_db, build_sha=new) == []


def test_server_without_a_build_commit_converges_nothing(
    test_db, bound_plan, monkeypatch
):
    pid, old, _, _ = bound_plan
    monkeypatch.delenv("YOKE_BUILD_SHA", raising=False)
    assert converge_source_bound_plans(test_db) == []
    assert _plan_state(test_db, pid) == (old, "run the frozen smoke command")


def test_boot_projection_converges_with_the_baked_build_commit(
    test_db, bound_plan, monkeypatch
):
    pid, old, new, _ = bound_plan
    monkeypatch.setenv("YOKE_BUILD_SHA", new)
    schema_init._converge_source_bound_plans(test_db)
    assert _plan_state(test_db, pid) == (new, "run the new smoke command")
