"""Report reads fail unreadable immediately; ordinary landing reads retry."""

from __future__ import annotations

import io
import urllib.error

from yoke_core.domain import gh_rest_transport as transport
from yoke_core.domain.merge_queue_read_reuse import MergeQueueReads
from yoke_core.domain.merge_queue_readiness import read_merge_queue_readiness
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from yoke_core.domain.steering_fleet_report_reads import FleetReportReads
from yoke_core.engines import merge_worktree_pr_check_runs as checks
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


def test_report_github_failure_is_unreadable_without_retry_backoff(monkeypatch):
    attempts = []
    sleeps = []
    auth = ProjectGithubAuth(project="sample", repo="owner/repo", token="fake")
    monkeypatch.setattr(checks, "resolve_auth_detail", lambda *_args: (auth, None))
    monkeypatch.setattr(transport, "sleep", sleeps.append)

    def unavailable(request, timeout):
        attempts.append(request.full_url)
        raise urllib.error.HTTPError(
            request.full_url, 503, "Service Unavailable", {},
            io.BytesIO(b'{"message":"Service Unavailable"}'),
        )

    monkeypatch.setattr(transport, "urlopen", unavailable)
    ctx = MergeContext(args=MergeArgs(branch="", target="main"), project="sample")

    def read(reads):
        return read_merge_queue_readiness(
            ctx, pr_number="42", target="main", reads=reads
        )

    report = FleetReportReads()
    landing = read(report.landings)
    assert landing.landing_state == "unreadable"
    assert landing.queue_entry_state == "unreadable"
    assert any("Service Unavailable" in warning for warning in landing.warnings)
    assert len(attempts) == 1  # One coherent PR document.
    assert sleeps == []
    assert read(report.landings) == landing
    assert len(attempts) == 1

    assert read(FleetReportReads().landings) == landing
    assert len(attempts) == 2
    assert sleeps == []

    assert read(MergeQueueReads()) == landing
    assert len(attempts) == 5  # The ordinary PR document retains three attempts.
    assert sleeps == [5, 15]
