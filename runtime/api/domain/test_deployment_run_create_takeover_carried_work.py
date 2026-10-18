"""Creating a run that takes over a waiting run reads carried work from it.

The unlocked creation pass only asks whether the waiting run could be taken
over, so its preceding release is an older succeeded run. The locked pass
settles the waiting run first, so the preceding release becomes that run and
carried work compares a different, shorter range over the same provider.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain import test_deployment_run_target_takeover as takeover_case
from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION
from yoke_core.domain import deployment_prepared_source as prepared
from yoke_core.domain import deployment_run_candidate_range as candidate_range
from yoke_core.domain import deployment_run_carried_work_repository as provider
from yoke_core.domain import deployment_run_create_composition as composition
from yoke_core.domain import deployment_run_create_write as create_write
from yoke_core.domain.deployment_run_carried_work import (
    carried_work_for_enrollment,
    parse_carried_work,
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


def test_a_takeover_create_reads_carried_work_from_the_taken_over_run(
    test_db: Any, monkeypatch
) -> None:
    takeover_case._seed_old(test_db, run_qa=False)
    takeover_case._close_passed(test_db)
    _seed_prior_release(test_db)
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

    created = create_write.create_run(
        "yoke",
        f"flow-{takeover_case.OLD}",
        release_lineage=NEW_LINEAGE,
        session_id=DRIVER_SESSION,
    )

    taken = takeover_case._run(test_db, takeover_case.OLD)
    assert taken["status"] == "succeeded"
    assert taken["superseded_by_run_id"] == created.run_id
    created_runs = test_db.execute(
        "SELECT id FROM deployment_runs WHERE supersedes_run_id=%s",
        (takeover_case.OLD,),
    ).fetchall()
    assert [row["id"] for row in created_runs] == [created.run_id]

    settled = _carried_work(test_db, takeover_case.OLD)
    assert settled["derivation"]["previous_run_id"] == PRIOR
    assert _shas(settled) == [WAITING_LINEAGE]

    carried = carried_work_for_enrollment(test_db, created.run_id)
    assert carried["derivation"]["previous_run_id"] == takeover_case.OLD
    assert carried["derivation"]["previous_release_lineage"] == WAITING_LINEAGE
    assert _shas(carried) == ["d" * 40, NEW_LINEAGE]


def _carried_work(conn: Any, run_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT carried_work FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    return parse_carried_work(row["carried_work"])


def _shas(carried: dict[str, Any]) -> list[str]:
    assert carried["derivation"]["contents_known"] is True
    return list(carried["commits"])
