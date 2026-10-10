"""Composition reports independent blockers for a pinned release candidate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)
from runtime.api.fixtures.bound_source_release import (
    CARRIER_FLOW,
    CARRIER_ITEM_ID,
    two_project_release,
)
from runtime.api.fixtures.carried_release_candidate import git
from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.deployment_run_create_write import cmd_create_run
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition
from yoke_core.domain.handlers.deployment_run_execution import (
    handle_deployment_execution_context,
)


def _blocked_candidate(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    release = two_project_release(test_db, tmp_path, monkeypatch)
    git(release["carrier_repo"], "commit", "--allow-empty", "-m", "Maintenance")
    unexplained = git(release["carrier_repo"], "rev-parse", "HEAD")
    environment = test_db.execute(
        "SELECT id FROM environments WHERE project_id=1 AND name='stage'"
    ).fetchone()[0]
    test_db.execute(
        "UPDATE deployment_runs SET release_lineage=%s,target_tier='persistent',"
        "target_environment_id=%s WHERE id='run-candidate'",
        (unexplained, environment),
    )
    test_db.execute(
        "UPDATE deployment_runs SET target_tier='persistent',"
        "target_environment_id=%s WHERE id='run-previous'",
        (environment,),
    )
    test_db.execute(
        "UPDATE items SET deployment_flow='different-release-flow' WHERE id=%s",
        (CARRIER_ITEM_ID,),
    )
    test_db.commit()
    return unexplained


def test_mixed_project_candidate_uses_the_bound_source_completion_authority(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = two_project_release(test_db, tmp_path, monkeypatch)

    valid, message = cmd_validate_composition("run-candidate")

    assert valid, message
    members = test_db.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id='run-candidate'"
    ).fetchall()
    assert len(members) == 2
    assert release["consumer_ref"] in message


def test_flow_mismatch_refuses_without_blocking_outside_commits(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unexplained = _blocked_candidate(test_db, tmp_path, monkeypatch)

    valid, message = cmd_validate_composition("run-candidate")

    assert not valid
    assert "selects completion flow 'different-release-flow'" in message
    assert unexplained not in message
    assert "made outside Yoke" not in message


def test_missing_completion_flow_still_refuses_with_outside_commits(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unexplained = _blocked_candidate(test_db, tmp_path, monkeypatch)
    test_db.execute(
        "UPDATE items SET deployment_flow=NULL WHERE id=%s", (CARRIER_ITEM_ID,)
    )
    test_db.commit()

    valid, message = cmd_validate_composition("run-candidate")

    assert not valid
    assert "no resolvable completion flow" in message
    assert unexplained not in message


def test_create_refuses_invalid_composition_without_reserving_a_run_id(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unexplained = _blocked_candidate(test_db, tmp_path, monkeypatch)
    environment = test_db.execute(
        "SELECT id FROM environments WHERE project_id=1 AND name='stage'"
    ).fetchone()[0]
    test_db.execute(
        "UPDATE deployment_flows SET status='active', target_tier='persistent',"
        "target_environment_id=%s WHERE id=%s",
        (environment, CARRIER_FLOW),
    )
    test_db.commit()
    before = test_db.execute("SELECT count(*) FROM deployment_runs").fetchone()[0]

    with pytest.raises(ValueError) as refusal:
        cmd_create_run("yoke", CARRIER_FLOW, release_lineage=unexplained)

    assert "selects completion flow 'different-release-flow'" in str(refusal.value)
    assert unexplained not in str(refusal.value)
    assert (
        test_db.execute("SELECT count(*) FROM deployment_runs").fetchone()[0] == before
    )


def test_start_context_refuses_before_returning_dispatchable_stages(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unexplained = _blocked_candidate(test_db, tmp_path, monkeypatch)
    monkeypatch.setattr(
        "yoke_core.domain.handlers.deployment_run_execution.require_run_driver",
        lambda _request, _run_id: None,
    )
    request = deployment_request(
        function="deployment_runs.execution.context",
        target=TargetRef(kind="workflow_run", workflow_run_id="run-candidate"),
    )

    outcome = handle_deployment_execution_context(request)

    assert not outcome.primary_success
    assert outcome.error is not None
    assert outcome.error.code == "composition_invalid"
    assert "selects completion flow 'different-release-flow'" in outcome.error.message
    assert unexplained not in outcome.error.message


def test_first_release_through_a_custody_flow_is_not_a_composition_blocker(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A flow's very first run has no predecessor, and that is an answer.

    Carried work is derived by comparing against the preceding succeeded run.
    With none, there is nothing to carry and nothing to repair, so composition
    must not report the baseline as unresolved deliverable code — a project
    could otherwise never create its first release through such a flow.
    """
    two_project_release(test_db, tmp_path, monkeypatch)
    test_db.execute(
        "UPDATE deployment_runs SET status='failed' WHERE id='run-previous'"
    )
    test_db.commit()

    valid, message = cmd_validate_composition("run-candidate")

    assert valid, message
    assert "no_prior_succeeded_run" not in message
