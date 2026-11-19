"""YOK-5522: a partly run execution moved by takeover resumes on the successor's build.

An execution that recorded a host-free case keeps its frozen target, so the
re-freeze paths leave it alone. On a channel target the controller compares
the channel's commit with the target's ``release_lineage``; the view handed
to a resume names the owner's lineage once the owner has deployed, while the
stored snapshot and digest stay bound to the results they proved.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from runtime.api.domain import deployment_qa_shared_plans_test_support as shared
from runtime.api.domain import deployment_run_target_takeover_test_support as takeover
from runtime.api.domain.deployment_qa_successor_retry_test_support import (
    _deploy_successor,
    _record,
    _seed_member_execution,
    _take_over,
)
from yoke_core.domain.deployment_qa_release_version import current_release_target
from yoke_core.domain.deployment_qa_execution_refreeze import resume_moved_execution
from yoke_core.domain.qa_controller_candidate import (
    QaControllerStaleTarget,
    controller_candidate,
)
from yoke_core.domain.qa_plan_execution_reentry import resume_execution
from yoke_core.domain.qa_plan_execution_store import (
    plan_execution_view,
    select_plan_execution,
)

BASE = "https://distribution.example.test"
PREDECESSOR_LINEAGE = "a" * 40  # the shared run's seeded release_lineage


@pytest.fixture
def channel(monkeypatch):
    """The installer origin's ``latest`` channel; tests set the commit it serves."""
    from yoke_contracts import resilient_fetch

    served = {"commit": PREDECESSOR_LINEAGE}

    def fetch(url, **_):
        assert url == f"{BASE}/dist/channels/latest.json", url
        body = {
            "version": f"0.2.0+{served['commit'][:6]}",
            "migration_history": {"source_commit": served["commit"]},
        }
        return SimpleNamespace(body=json.dumps(body).encode())

    monkeypatch.setattr(resilient_fetch, "fetch_bytes", fetch)
    return served


def _channel_environment(conn) -> None:
    """The QA destination follows a release channel and pins no release."""
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
        "SELECT id,1,'stage','https://preview.example.test',%s,%s FROM sites "
        "WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO UPDATE SET settings=EXCLUDED.settings",
        (
            json.dumps(
                {
                    "role": {"production": False},
                    "distribution": {"base_url": BASE, "channel": "latest"},
                }
            ),
            "2026-09-14T00:00:00Z",
        ),
    )


def _stored(conn, execution_id):
    return conn.execute(
        "SELECT execution_target_json,execution_target_digest,execution_order,"
        "cursor_ordinal FROM qa_plan_executions WHERE id=%s",
        (execution_id,),
    ).fetchone()


def _partly_run_execution(conn, monkeypatch):
    _channel_environment(conn)
    execution = _seed_member_execution(conn, monkeypatch)
    target = execution["execution_target"]
    assert "release_version" not in target["endpoints"]
    assert target["endpoints"]["release_channel"] == "latest"
    assert target["deployment"]["release_lineage"] == PREDECESSOR_LINEAGE
    _record(conn, execution, 0, "pass")
    conn.commit()
    return execution


def test_moved_partly_run_execution_resumes_on_the_successor_lineage(
    test_db, monkeypatch, channel
):
    execution = _partly_run_execution(test_db, monkeypatch)
    before = _stored(test_db, execution["id"])
    assert before["cursor_ordinal"] == 1

    _take_over(test_db)
    moved = select_plan_execution(test_db, execution["id"], lock=False)
    assert moved["deployment_run_id"] == takeover.NEW
    # Before the successor deploys, the destination still serves the frozen build.
    view = plan_execution_view(test_db, moved)
    assert view["execution_target"]["deployment"]["release_lineage"] == PREDECESSOR_LINEAGE
    assert controller_candidate(view).source_commit == PREDECESSOR_LINEAGE

    _deploy_successor(test_db)
    channel["commit"] = takeover.NEW_LINEAGE
    # The host-turn wake resumes by execution id; a begun execution keeps its
    # frozen target, so no re-freeze applies and the view carries the move.
    moved = select_plan_execution(test_db, execution["id"], lock=False)
    assert resume_moved_execution(test_db, moved, None, None) is None
    resumed = resume_execution(test_db, moved)
    assert resumed["execution_id"] == execution["id"]
    assert resumed["execution_target"]["deployment"]["release_lineage"] == takeover.NEW_LINEAGE
    candidate = controller_candidate(resumed)
    assert candidate is not None and candidate.source_commit == takeover.NEW_LINEAGE

    after = _stored(test_db, execution["id"])
    assert after["execution_order"] == before["execution_order"]
    assert after["cursor_ordinal"] == 1
    # View-only: the stored snapshot and digest still name the target the result proved.
    assert after["execution_target_json"] == before["execution_target_json"]
    assert after["execution_target_digest"] == before["execution_target_digest"]
    assert [row["requirement_id"] for row in resumed["results"]] == [
        int(execution["roster"][0]["requirement_id"])
    ]


def test_the_candidate_check_still_refuses_a_channel_off_the_owner_build(
    test_db, monkeypatch, channel
):
    execution = _partly_run_execution(test_db, monkeypatch)
    _take_over(test_db)
    _deploy_successor(test_db)
    view = plan_execution_view(
        test_db, select_plan_execution(test_db, execution["id"], lock=False)
    )
    # The channel still serves the predecessor: the owner's build is not live.
    with pytest.raises(QaControllerStaleTarget, match="qa_controller_not_candidate"):
        controller_candidate(view)


def test_a_target_its_owner_did_not_inherit_is_returned_unchanged(
    test_db, monkeypatch
):
    execution = _partly_run_execution(test_db, monkeypatch)
    # A deployed run that never took over the shared run.
    test_db.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,target_tier,target_environment_id,"
        "release_lineage,status,created_at,composition_frozen_at,requirement_snapshot) "
        "SELECT %s,project_id,flow,target_tier,target_environment_id,%s,'created',"
        "created_at,composition_frozen_at,requirement_snapshot FROM deployment_runs "
        "WHERE id=%s",
        (takeover.NEW, takeover.NEW_LINEAGE, shared.RUN),
    )
    _deploy_successor(test_db)
    target = execution["execution_target"]
    assert current_release_target(test_db, takeover.NEW, target) is target
