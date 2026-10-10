"""Concurrency waits cannot be inferred to be dead from zero jobs or age."""

from datetime import datetime, timezone

import pytest

from yoke_core.domain.github_actions_run_stall import (
    CI_RUN_NEVER_STARTED_REASON,
    pending_run_message,
    run_concurrency_groups,
)


@pytest.mark.parametrize("groups", [None, ("release",)])
def test_old_pending_waits_with_configured_or_unknown_concurrency(groups):
    message = pending_run_message(
        repo="owner/repo",
        run_id="10",
        jobs_count=0,
        updated_at="2000-01-01T00:00:00Z",
        concurrency_groups=groups,
    )

    assert message.startswith("pending run=10")
    assert CI_RUN_NEVER_STARTED_REASON not in message


@pytest.mark.parametrize("members", [[], [{"run_id": 10, "status": "pending"}]])
def test_configured_group_explains_wait_even_between_admissions(members):
    assert run_concurrency_groups(
        {
            "total_count": 1,
            "concurrency_groups": [{"group_name": "release", "group_members": members}],
        }
    ) == ("release",)


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {"total_count": True, "concurrency_groups": []},
        {"total_count": 2, "concurrency_groups": []},
        {"total_count": 1, "concurrency_groups": [{}]},
    ],
)
def test_missing_or_partial_evidence_cannot_prove_absence_of_concurrency(data):
    with pytest.raises(ValueError):
        run_concurrency_groups(data)


@pytest.mark.parametrize(
    "jobs,updated",
    [(1, "2000-01-01T00:00:00Z"), (0, "2026-10-01T00:00:00Z"), (0, None)],
)
def test_unqueued_run_needs_stale_zero_job_evidence_to_stall(jobs, updated):
    message = pending_run_message(
        repo="owner/repo",
        run_id="10",
        jobs_count=jobs,
        updated_at=updated,
        concurrency_groups=(),
        observed_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    assert CI_RUN_NEVER_STARTED_REASON not in message
