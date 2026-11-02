"""Deployment recovery messages keep the run that failed and its connection."""

from types import SimpleNamespace
from unittest import mock

import pytest

from yoke_core.domain import deploy_pipeline_pinned_source as pinned
from yoke_core.domain import deploy_pipeline_fleet_release_source as release_source
from yoke_core.domain import deploy_pipeline_fleet_rehearsal as rehearsal
from yoke_core.domain import deploy_pipeline_fleet_rehearsal_sources as sources
from yoke_core.domain import deployment_run_contained_items as containment
from yoke_core.domain import deployment_run_collective_finalization as settlement
from yoke_core.domain import deployment_run_stale_bound_sources as stale
from yoke_core.domain import delivery_member_close_steps as close
from yoke_core.domain import qa_plan_empty_roster as roster
from yoke_core.domain.deploy_pipeline_ci_recovery import ci_adapter_failure_message
from yoke_core.domain import deployment_run_recovery_command as recovery

RUN = "run-needing-recovery"


@pytest.fixture(autouse=True)
def connection(monkeypatch):
    monkeypatch.setattr(recovery.machine_config, "active_env", lambda: "release-prod")


def assert_recipe(message):
    assert f"yoke --env release-prod watch deploy -- {RUN}" in message
    assert "RUN-ID" not in message


def test_missing_pinned_commit_names_run(monkeypatch):
    monkeypatch.setattr(pinned, "_resolve_commit", lambda *_: "")
    monkeypatch.setattr(
        pinned.repo_upstream_git,
        "git",
        lambda *_a, **_k: SimpleNamespace(
            returncode=1, stdout="", stderr="unavailable"
        ),
    )
    with pytest.raises(pinned.DeployPinnedSourceError) as failure:
        pinned._ensure_commit("/checkout", "missing", RUN)
    assert_recipe(str(failure.value))


def test_unresolved_self_release_project_names_run(monkeypatch):
    monkeypatch.setattr(pinned, "project_id_for_slug", lambda _: None)
    with pytest.raises(pinned.DeployPinnedSourceError) as failure:
        pinned.self_release_checkout("project", RUN)
    assert_recipe(str(failure.value))


def test_missing_fleet_source_commit_names_run(monkeypatch):
    monkeypatch.setattr(
        release_source.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(
            returncode=1, stdout="", stderr="unavailable"
        ),
    )
    assert_recipe(release_source.ensure_commit("/checkout", "missing", RUN))


def test_missing_bound_commit_names_run():
    _, refusal = sources.bound_commits(
        {"source": {"project": "consumer"}}, {}, run_id=RUN
    )
    assert_recipe(refusal)


def test_unreadable_fleet_coverage_names_run(monkeypatch):
    monkeypatch.setattr(rehearsal, "read_coverage", lambda **_: ({}, "unreadable"))
    _, refusal = rehearsal._coverage("project", "primary", "prod", (), "digest", RUN)
    assert_recipe(refusal)


def test_github_outage_names_run():
    assert_recipe(
        ci_adapter_failure_message(
            "github_unavailable",
            "unavailable",
            workflow="ci.yml",
            repo="owner/repo",
            run_id=RUN,
        )
    )


def test_containment_without_checkout_names_run():
    basis = {
        "projects": [{"project_id": 1, "project": "project", "items": [{"id": 2}]}]
    }
    with pytest.raises(containment.CandidateContainmentRefusal) as failure:
        containment.attest_candidate_containment(basis, lambda _: "", run_id=RUN)
    assert_recipe(str(failure.value))


def test_lost_settlement_transaction_names_run():
    conn = mock.Mock()
    conn.execute.side_effect = RuntimeError("savepoint vanished")
    with pytest.raises(settlement.SettlementTransactionLost) as failure:
        settlement._end_savepoint(conn, "member", keep=True, run_id=RUN)
    assert_recipe(str(failure.value))


def test_missing_close_evidence_names_run(monkeypatch):
    monkeypatch.setattr(
        close,
        "load_item_workflow_runtime",
        lambda *_: SimpleNamespace(workflow_id="dash"),
    )
    monkeypatch.setattr(
        close, "evaluate_dash_evidence", lambda *_: SimpleNamespace(missing=("result",))
    )
    assert_recipe(close.member_close_evidence_refusal(None, item_id=1, run_id=RUN))


def test_unresolved_release_output_parent_names_run(monkeypatch):
    from yoke_core.domain import deployment_run_release_output as output
    from yoke_core.domain import deployment_run_carried_work_source as source

    monkeypatch.setattr(
        output, "release_output_runs", lambda *_: {"head": {"run_id": "producer"}}
    )
    monkeypatch.setattr(
        source,
        "open_carried_work_source",
        lambda *_: SimpleNamespace(resolve_commit=lambda _: ""),
    )
    _, refusal = stale._release_output_on_frozen(
        None, run_id=RUN, project_id=1, frozen="base", current="head"
    )
    assert_recipe(refusal)


def test_discharged_roster_names_run():
    assert_recipe(
        roster.discharged_without_cases_statement(
            requirement_id=1, qa_kind="no-obligation", run_id=RUN
        )
    )


def test_discharge_without_requirement_still_names_run(monkeypatch):
    from yoke_core.domain import post_deploy_verification_answer as answer

    monkeypatch.setattr(
        answer,
        "answer_for_item",
        lambda *_: SimpleNamespace(discharges_without_cases=True, verdict="none"),
    )
    monkeypatch.setattr(roster, "recorded_discharge", lambda *_: None)
    assert_recipe(roster.member_discharge_statement(None, 1, RUN))
