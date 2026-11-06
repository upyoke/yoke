# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.domain import ci_run_redispatch, merge_queue_entry_check_redispatch

from yoke_core.domain.ci_job_outcome import CI_JOB_NOT_STARTED

from yoke_core.domain.merge_queue_enqueue_verification import red_entry_checks_refusal

from yoke_core.domain.merge_queue_entry_checks import (
    entry_checks_refusal,
    only_no_verdict,
    regate_instruction,
)

from yoke_core.engines.merge_worktree_pr_check_runs import LandingCheck

from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext

RUN_URL = "https://github.com/o/r/actions/runs/37365021162/job/111944546142"

CANCELLED_REQUIRED = LandingCheck(
    name="repo-contracts",
    status="completed",
    conclusion="cancelled",
    required=True,
    url=RUN_URL,
)

FAILED_REQUIRED = LandingCheck(
    name="container",
    status="completed",
    conclusion="failure",
    required=True,
    url="https://github.com/o/r/actions/runs/37365021163/job/9",
)

QUEUED_REQUIRED = LandingCheck(
    name="repo-contracts", status="queued", required=True, url=RUN_URL
)


def _rerun_fakes(monkeypatch, *, post_error=None, started=True):
    posts = []

    def request(req, *, token, max_attempts=None):
        if req.method == "POST":
            assert max_attempts == 1
            posts.append((req.method, req.path, token))
            if post_error is not None:
                raise post_error
            return SimpleNamespace(status=201, body={})
        if "/pulls/" in req.path:
            body = {
                "state": "open",
                "head": {"sha": "1" * 40, "ref": "ALP-1", "repo": {"full_name": "o/r"}},
            }
        elif req.path.endswith("/jobs"):
            body = {
                "jobs": [
                    {
                        "check_run_url": "https://api.github.com/repos/o/r/check-runs/7",
                        "runner_name": "runner" if started else "",
                        "steps": [{}] if started else [],
                        "conclusion": "cancelled",
                    }
                ]
            }
        elif req.path.endswith("/annotations"):
            body = []
        elif "/actions/workflows/" in req.path:
            body = {"workflow_runs": [{"id": 37365021162}]}
        else:
            body = {
                "id": 37365021162,
                "workflow_id": 1,
                "head_sha": "1" * 40,
                "head_branch": "ALP-1",
                "status": "completed",
                "conclusion": "cancelled",
                "run_attempt": 1,
            }
        return SimpleNamespace(status=200, body=body)

    monkeypatch.setattr(
        merge_queue_entry_check_redispatch,
        "resolve_auth_detail",
        lambda _ctx, _perms: (SimpleNamespace(repo="o/r", token="tok"), None),
    )
    monkeypatch.setattr(
        "yoke_core.domain.github_actions_rest.request_with_retry", request
    )
    return posts
