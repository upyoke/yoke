"""Takeover preparation predicts settlement without changing the waiting run."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

import pytest

from runtime.api.domain import test_deployment_run_target_takeover as takeover_case
from runtime.api.fixtures.backlog import insert_item, insert_item_worktree
from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION
from yoke_core.domain import deployment_prepared_source as prepared
from yoke_core.domain import deployment_run_candidate_range as candidate_range
from yoke_core.domain import deployment_run_carried_work_repository as provider
from yoke_core.domain import deployment_run_create_composition as composition
from yoke_core.domain import deployment_run_create_write as create_write
from yoke_core.domain import deployment_runs_validation as validate
from yoke_core.domain.deployment_run_carried_work import (
    carried_work_for_enrollment,
    parse_carried_work,
)
from yoke_core.domain.deployment_source_reads import (
    SourcePreparationChanged,
    source_read,
)

PRIOR = "run-takeover-prior"
PRIOR_LINEAGE = "a" * 40
WAITING_LINEAGE = takeover_case.OLD_LINEAGE
NEW_LINEAGE = takeover_case.NEW_LINEAGE


def _commit(sha: str, parent: str) -> dict[str, Any]:
    return {
        "sha": sha,
        "commit": {
            "message": f"commit {sha[:7]}",
            "committer": {"date": "2026-10-17T00:00:00Z"},
            "author": {"name": "A contributor"},
        },
        "parents": [{"sha": parent}],
    }


#: ``a -> b -> d -> c``: the prior release, the waiting run, one more commit
#: and the new candidate. Each comparison lists only its own range; the
#: settled run's own ``a...b`` is recorded once the creation commits.
COMPARISONS = {
    (PRIOR_LINEAGE, WAITING_LINEAGE): [_commit(WAITING_LINEAGE, PRIOR_LINEAGE)],
    (PRIOR_LINEAGE, NEW_LINEAGE): [
        _commit(WAITING_LINEAGE, PRIOR_LINEAGE),
        _commit("d" * 40, WAITING_LINEAGE),
        _commit(NEW_LINEAGE, "d" * 40),
    ],
    (WAITING_LINEAGE, NEW_LINEAGE): [
        _commit("d" * 40, WAITING_LINEAGE),
        _commit(NEW_LINEAGE, "d" * 40),
    ],
}


def _provider(request: Any, *, token: str) -> Any:
    del token
    base, head = request.path.rsplit("/", 1)[-1].split("...")
    commits = COMPARISONS[(base, head)]
    body = {"status": "ahead", "total_commits": len(commits), "commits": commits}
    return type("Response", (), {"status": 200, "headers": {}, "body": body})()


def _open_provider(conn: Any, project_id: int, repo_root: Any = None) -> Any:
    del conn, project_id, repo_root
    return provider.RepositoryProviderSource("owner/repo", "token")


def _seed_prior_release(conn: Any) -> None:
    """A succeeded release on the same target, older than the waiting run."""
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,target_tier,"
        "target_environment_id,release_lineage,status,current_stage,created_at,"
        "completed_at) SELECT %s,project_id,flow,target_tier,"
        "target_environment_id,%s,'succeeded','complete',created_at,created_at "
        "FROM deployment_runs WHERE id=%s",
        (PRIOR, PRIOR_LINEAGE, takeover_case.OLD),
    )
    conn.execute(
        "UPDATE deployment_flows SET status='active' WHERE id=%s",
        (f"flow-{takeover_case.OLD}",),
    )
    conn.commit()


@pytest.mark.parametrize(
    "run_qa,delivered", [(False, True), (False, False), (True, True)]
)
def test_a_takeover_create_prepares_the_settled_release_base_in_one_pass(
    test_db: Any,
    monkeypatch,
    run_qa,
    delivered,
) -> None:
    takeover_case._seed_old(test_db, run_qa=run_qa)
    if delivered:
        takeover_case._close_passed(test_db)
    _seed_prior_release(test_db)
    # More distinct landed tips than the creation retry budget: changing the
    # predecessor must not discover each carrying_commit fact under locks.
    for offset in range(12):
        item_id = 10000 + offset
        insert_item(
            test_db,
            id=item_id,
            workflow_id="dash",
            status="done",
            merged_at="2026-10-16T00:00:00Z",
        )
        lane = insert_item_worktree(
            test_db,
            item_id=item_id,
            branch=f"landed-{offset}",
            state="active",
        )
        test_db.execute(
            "UPDATE item_worktrees SET commit_sha=%s WHERE id=%s",
            (f"{offset + 100:040x}", lane["id"]),
        )
    test_db.commit()
    takeover_case._contains(monkeypatch)
    monkeypatch.setattr(provider, "request_with_retry", _provider)
    monkeypatch.setattr(prepared, "open_carried_work_source", _open_provider)
    monkeypatch.setattr(candidate_range, "open_carried_work_source", _open_provider)
    # The seeded flow's stages are fixtures, not an executable definition, so
    # the new run takes the waiting run's target without judging the flow.
    target = test_db.execute(
        "SELECT target_tier,target_environment_id FROM deployment_runs WHERE id=%s",
        (takeover_case.OLD,),
    ).fetchone()
    for module in (composition, create_write):
        monkeypatch.setattr(module, "run_target", lambda *_: tuple(target))
        monkeypatch.setattr(module, "refuse_run_that_cannot_execute", lambda *_: None)

    validation_members = []
    original_validate = validate.cmd_validate_composition

    def check_members(run_id, **kwargs):
        validation_members.append(takeover_case._members(test_db, run_id))
        return original_validate(run_id, **kwargs)

    monkeypatch.setattr(validate, "cmd_validate_composition", check_members)
    steps = []
    timed = create_write.timed_preparation

    def record_step(name, function, *args, **kwargs):
        steps.append(name)
        result = timed(name, function, *args, **kwargs)
        if name == "create_provisional_composition":
            old = takeover_case._run(test_db, takeover_case.OLD)
            assert old["status"] == "executing"
            assert old["superseded_by_run_id"] is None
            assert takeover_case._members(test_db, takeover_case.OLD) == {
                takeover_case.PASSED,
                takeover_case.WAITING,
            }
        return result

    monkeypatch.setattr(create_write, "timed_preparation", record_step)

    created = create_write.create_run(
        "yoke",
        f"flow-{takeover_case.OLD}",
        release_lineage=NEW_LINEAGE,
        session_id=DRIVER_SESSION,
    )
    expected_members = (
        {takeover_case.WAITING}
        if delivered
        else {takeover_case.PASSED, takeover_case.WAITING}
    )
    assert validation_members == [expected_members, expected_members]
    assert steps.count("create_lock") == 1
    assert "create_source_refresh" not in steps

    taken = takeover_case._run(test_db, takeover_case.OLD)
    succeeded = delivered and not run_qa
    assert taken["status"] == ("succeeded" if succeeded else "cancelled")
    assert taken["superseded_by_run_id"] == created.run_id
    created_runs = test_db.execute(
        "SELECT id FROM deployment_runs WHERE supersedes_run_id=%s",
        (takeover_case.OLD,),
    ).fetchall()
    assert [row["id"] for row in created_runs] == [created.run_id]

    if succeeded:
        settled = _carried_work(test_db, takeover_case.OLD)
        assert settled["derivation"]["previous_run_id"] == PRIOR
        assert _shas(settled) == [WAITING_LINEAGE]

    carried = carried_work_for_enrollment(test_db, created.run_id)
    assert carried["derivation"]["previous_run_id"] == (
        takeover_case.OLD if succeeded else PRIOR
    )
    assert carried["derivation"]["previous_release_lineage"] == (
        WAITING_LINEAGE if succeeded else PRIOR_LINEAGE
    )
    assert _shas(carried) == (
        ["d" * 40, NEW_LINEAGE]
        if succeeded
        else [WAITING_LINEAGE, "d" * 40, NEW_LINEAGE]
    )


def _carried_work(conn: Any, run_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT carried_work FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    return parse_carried_work(row["carried_work"])


def _shas(carried: dict[str, Any]) -> list[str]:
    assert carried["derivation"]["contents_known"] is True
    return list(carried["commits"])


def test_exhausted_create_preparation_teaches_creation_recovery(monkeypatch):
    class Connection:
        def execute(self, *_):
            pass

        def rollback(self):
            pass

    conn = Connection()
    attempts = []

    def changing_source(conn, *_args, **_kwargs):
        attempts.append(len(attempts))
        return source_read(conn, ("changing", len(attempts)), lambda: None)

    monkeypatch.setattr(
        create_write.db_backend, "connection_is_postgres", lambda _: True
    )
    monkeypatch.setattr(create_write, "validate_before_lock", lambda *_a, **_k: None)
    monkeypatch.setattr(create_write, "bounded_run_write", lambda *_: nullcontext())
    monkeypatch.setattr(create_write, "_create_locked", changing_source)
    with pytest.raises(SourcePreparationChanged) as refused:
        create_write._create_committed(conn, "project", {}, {})
    assert len(attempts) == 8
    message = str(refused.value)
    assert "deployment_source_preparation_changed" in message
    assert "Repeat the same deployment-runs create or start-for-item command" in message
    assert "original arguments and idempotency key" in message
    assert "Re-drive the same run" not in message
