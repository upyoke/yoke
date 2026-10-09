"""GitHub clock ingress and native token/stall thresholds."""

from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain.github_app_token_models import (
    GitHubAppTokenError,
    InstallationToken,
    ensure_utc,
    parse_github_datetime,
)
from yoke_core.domain.github_actions_run_stall import pending_run_message
from yoke_core.domain.handlers.github_actions_run import RunGetRequest, _classify
from yoke_core.domain.project_github_auth_models import ProjectGithubAuth
from yoke_core.engines import merge_worktree_pr_graphql as graphql


@pytest.mark.parametrize("offset", [0, -240, 345])
def test_token_facts_and_skew_keep_microsecond_precision(monkeypatch, offset):
    now = parse_instant("2026-07-09T17:00:00.000001Z")
    zone = timezone(timedelta(minutes=offset))
    issued = (now - timedelta(seconds=300, microseconds=-1)).astimezone(zone)
    expiry = (now + timedelta(seconds=60, microseconds=1)).astimezone(zone)
    auth = ProjectGithubAuth(
        project="project",
        repo="owner/repo",
        token="redacted",
        token_issued_at=issued,
        token_expires_at=expiry,
    )
    monkeypatch.setattr(graphql, "clock", lambda: now)
    assert auth.token_issued_at == issued
    assert auth.token_issued_at.tzinfo == timezone.utc
    assert graphql._token_age_seconds(auth.token_issued_at) == 299
    assert graphql._token_age_seconds(None) is None
    assert InstallationToken(token="redacted", expires_at=expiry).usable_at(now)
    assert not InstallationToken(
        token="redacted", expires_at=now + timedelta(seconds=60)
    ).usable_at(now)
    assert (
        parse_github_datetime("2026-07-09T22:45:00.000001+05:45", "expires_at") == now
    )


@pytest.mark.parametrize(
    "invalid",
    [
        "",
        "null",
        "2026-07-09T17:00:00",
        "2026-07-09T17:00:00-00:00",
        1770000000,
        datetime(2026, 7, 9),
    ],
)
def test_provider_clocks_refuse_inference(invalid):
    with pytest.raises(GitHubAppTokenError, match="invalid_instant"):
        parse_github_datetime(invalid, "expires_at")
    with pytest.raises(InvalidInstant):
        pending_run_message(
            repo="owner/repo",
            run_id="1",
            jobs_count=0,
            updated_at=invalid,
            concurrency_groups=(),
        )


def test_native_authorization_refuses_non_native_facts():
    with pytest.raises(InvalidInstant):
        ProjectGithubAuth(
            project="project",
            repo="owner/repo",
            token="redacted",
            token_issued_at="2026-07-09T17:00:00Z",
        )
    with pytest.raises(InvalidInstant):
        ensure_utc(datetime(2026, 7, 9))


@pytest.mark.parametrize("offset", [0, -240, 345])
def test_actions_stall_threshold_and_wire_projection(offset):
    now = parse_instant("2026-07-09T17:00:00.000001Z")
    zone = timezone(timedelta(minutes=offset))

    def message(updated):
        return pending_run_message(
            repo="owner/repo",
            run_id="1",
            jobs_count=0,
            updated_at=updated,
            observed_at=now,
            concurrency_groups=(),
        )

    assert message(
        (now - timedelta(seconds=120, microseconds=-1)).astimezone(zone)
    ).startswith("pending")
    assert message((now - timedelta(seconds=120)).astimezone(zone)).startswith(
        "stalled_dispatch"
    )
    assert "updated_at=2026-07-09T16:58:00.000001Z" in message(
        now - timedelta(seconds=120)
    )
    assert message(None).startswith("pending")
    payload = RunGetRequest(repo="owner/repo", run_id="1", project="project")
    response = _classify(
        payload, {"status": "in_progress", "updated_at": now.astimezone(zone)}
    )
    assert response.updated_at == "2026-07-09T17:00:00.000001Z"
    assert _classify(payload, {"status": "in_progress"}).updated_at is None
