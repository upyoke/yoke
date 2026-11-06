# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from contextlib import nullcontext

from typing import Any

import pytest

from runtime.api.domain import deployment_run_target_takeover_test_support as takeover_case

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
