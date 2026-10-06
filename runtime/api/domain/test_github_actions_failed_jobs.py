"""Regressions for reading every failed job of one run.

A sharded run fails in several jobs at once. These cover that each of
them is read by its own job id — including while sibling jobs still
run — that the job inventory follows provider pagination, and that a
job whose log GitHub will not hand over carries a named reason rather
than vanishing. Rendering is covered by
``test_github_actions_failed_job_report.py``.
"""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any, Dict, List

import pytest

from yoke_core.domain import gh_rest_transport, github_actions_logs
from yoke_core.domain import github_actions_failed_jobs as failed_jobs_module
from yoke_core.domain.gh_rest_transport import RestNotFoundError, RestTransportError
from yoke_core.domain.github_actions_failed_jobs import (
    JOBS_PAGE_SIZE,
    LOG_AVAILABLE,
    LOG_EXPIRED_OR_MISSING,
    LOG_FETCH_FAILED,
    LOG_PERMISSION_DENIED,
    FailedJob,
    collect_failed_jobs,
    list_run_jobs,
    resolve_log_downloads,
)


SHARD_NAMES = (
    "test-shard (3.10, 6)",
    "test-shard (3.10, 7)",
    "test-shard (3.13, 6)",
    "test-shard (3.13, 7)",
)


def _job(
    index: int,
    name: str,
    conclusion: str | None = "failure",
    status: str = "completed",
) -> Dict[str, Any]:
    return {
        "id": 900 + index,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "html_url": f"https://github.com/o/r/actions/runs/123/job/{900 + index}",
    }


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.status = 200
        self.headers: Dict[str, str] = {}

    def read(self, size: int = -1) -> bytes:
        return self._payload if size < 0 else self._payload[:size]

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> None:
        return None


def _http_error(status: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.github.com/x", status, "synthetic", {}, io.BytesIO(body)
    )


def _install_job_listings(monkeypatch, pages: List[Dict[str, Any]]) -> List[str]:
    """Answer the run-jobs REST reads with *pages*, in order."""
    calls: List[str] = []
    iterator = iter(pages)

    def _fake(request, timeout=None):
        calls.append(request.full_url)
        return _FakeResponse(json.dumps(next(iterator)).encode("utf-8"))

    monkeypatch.setattr(gh_rest_transport, "urlopen", _fake)
    return calls


def _install_log_responses(monkeypatch, responses: List[Any]) -> List[str]:
    """Answer the per-job log reads with *responses*, in order."""
    calls: List[str] = []
    iterator = iter(responses)

    def _fake(request, timeout=None):
        calls.append(request.full_url)
        payload = next(iterator)
        if isinstance(payload, Exception):
            raise payload
        return _FakeResponse(payload)

    monkeypatch.setattr(github_actions_logs, "urlopen", _fake)
    monkeypatch.setattr(github_actions_logs, "sleep", lambda _s: None)
    return calls


class TestCollectFailedJobs:
    def test_every_failed_shard_is_read_by_its_own_job_id(self, monkeypatch):
        _install_job_listings(
            monkeypatch,
            [
                {
                    "total_count": 4,
                    "jobs": [_job(i, n) for i, n in enumerate(SHARD_NAMES)],
                }
            ],
        )
        calls = _install_log_responses(
            monkeypatch, [f"FAILED signature {i}".encode() for i in range(4)]
        )

        failures = collect_failed_jobs("o/r", "123", token="ghs_x")

        assert [job.name for job in failures.failed] == list(SHARD_NAMES)
        assert [job.log_text for job in failures.failed] == [
            f"FAILED signature {i}" for i in range(4)
        ]
        assert {job.log_status for job in failures.failed} == {LOG_AVAILABLE}
        assert calls == [
            f"https://api.github.com/repos/o/r/actions/jobs/{900 + i}/logs"
            for i in range(4)
        ]
        assert failures.unfinished_job_count == 0

    def test_finished_failure_is_read_while_siblings_still_run(self, monkeypatch):
        """A red shard is readable before the run concludes."""
        _install_job_listings(
            monkeypatch,
            [
                {
                    "total_count": 3,
                    "jobs": [
                        _job(0, "shard 1"),
                        _job(1, "shard 2", conclusion=None, status="in_progress"),
                        _job(2, "shard 3", conclusion=None, status="queued"),
                    ],
                }
            ],
        )
        calls = _install_log_responses(
            monkeypatch, [b"FAILED test_a - assert 1 == 2\n"]
        )

        failures = collect_failed_jobs("o/r", "123", token="ghs_x")

        [job] = failures.failed
        assert job.name == "shard 1"
        assert "assert 1 == 2" in job.log_text
        assert failures.unfinished_job_count == 2
        assert calls == ["https://api.github.com/repos/o/r/actions/jobs/900/logs"]

    def test_successful_jobs_are_not_read(self, monkeypatch):
        _install_job_listings(
            monkeypatch,
            [
                {
                    "total_count": 2,
                    "jobs": [
                        _job(0, "build", conclusion="failure"),
                        _job(1, "lint", conclusion="success"),
                    ],
                }
            ],
        )
        calls = _install_log_responses(monkeypatch, [b"boom"])

        failures = collect_failed_jobs("o/r", "123", token="ghs_x")

        assert [job.name for job in failures.failed] == ["build"]
        assert len(calls) == 1

    def test_run_with_no_failures_collects_nothing_without_fetching_logs(
        self, monkeypatch
    ):
        _install_job_listings(
            monkeypatch,
            [{"total_count": 1, "jobs": [_job(0, "build", conclusion="success")]}],
        )
        log_calls = _install_log_responses(monkeypatch, [])

        assert collect_failed_jobs("o/r", "123", token="ghs_x").failed == []
        assert log_calls == []

    def test_expired_job_log_is_reported_not_dropped(self, monkeypatch):
        _install_job_listings(
            monkeypatch,
            [{"total_count": 2, "jobs": [_job(0, "build"), _job(1, "test")]}],
        )
        _install_log_responses(monkeypatch, [b"build boom", _http_error(404)])

        failures = collect_failed_jobs("o/r", "1", token="ghs_x")
        jobs = {job.name: job for job in failures.failed}

        assert set(jobs) == {"build", "test"}
        assert jobs["test"].log_status == LOG_EXPIRED_OR_MISSING
        assert "expire" in jobs["test"].log_detail

    def test_permission_denied_job_log_is_reported_not_dropped(self, monkeypatch):
        _install_job_listings(
            monkeypatch,
            [{"total_count": 1, "jobs": [_job(0, "build")]}],
        )
        _install_log_responses(monkeypatch, [_http_error(403, b"forbidden")])

        [job] = collect_failed_jobs("o/r", "1", token="ghs_x").failed

        assert job.log_status == LOG_PERMISSION_DENIED
        assert "Actions read" in job.log_detail

    def test_oversized_job_log_names_the_full_capture_recovery(self, monkeypatch):
        _install_job_listings(
            monkeypatch,
            [{"total_count": 1, "jobs": [_job(0, "build")]}],
        )
        monkeypatch.setattr(
            github_actions_logs, "GITHUB_ACTIONS_JOB_LOG_LIMIT_BYTES", 4
        )
        _install_log_responses(monkeypatch, [b"0123456789"])

        [job] = collect_failed_jobs("o/r", "1", token="ghs_x").failed

        assert job.log_status == LOG_FETCH_FAILED
        assert "--full" in job.log_detail


class TestResolveLogDownloads:
    def test_maps_each_job_to_its_signed_download_address(self, monkeypatch):
        jobs = [_failed_job("901"), _failed_job("902")]

        def _fake(_repo, job_id, *, token):
            return f"https://results.example/{job_id}.txt?sig=x"

        monkeypatch.setattr(failed_jobs_module, "job_log_download_url", _fake)

        downloads = resolve_log_downloads("o/r", jobs, token="ghs_x")

        assert downloads["901"].url == "https://results.example/901.txt?sig=x"
        assert downloads["902"].detail == ""

    def test_refused_address_carries_a_named_reason(self, monkeypatch):
        def _fake(_repo, _job_id, *, token):
            raise RestNotFoundError("HTTP 410: gone", status=410)

        monkeypatch.setattr(failed_jobs_module, "job_log_download_url", _fake)

        [download] = resolve_log_downloads(
            "o/r", [_failed_job("901")], token="ghs_x"
        ).values()

        assert download.url == ""
        assert "expire" in download.detail


def _failed_job(job_id: str) -> FailedJob:
    return FailedJob(
        job_id=job_id,
        name=f"job {job_id}",
        conclusion="failure",
        html_url="",
        log_text="",
        log_status=LOG_AVAILABLE,
        log_detail="",
    )


class TestListRunJobs:
    def test_follows_pagination_past_the_first_page(self, monkeypatch):
        first = [_job(i, f"shard {i}") for i in range(JOBS_PAGE_SIZE)]
        second = [_job(JOBS_PAGE_SIZE, "shard last")]
        calls = _install_job_listings(
            monkeypatch,
            [
                {"total_count": JOBS_PAGE_SIZE + 1, "jobs": first},
                {"total_count": JOBS_PAGE_SIZE + 1, "jobs": second},
            ],
        )

        jobs = list_run_jobs("o/r", "123", token="ghs_x")

        assert len(jobs) == JOBS_PAGE_SIZE + 1
        assert jobs[-1]["name"] == "shard last"
        assert "page=1" in calls[0] and "page=2" in calls[1]

    def test_single_short_page_issues_one_read(self, monkeypatch):
        calls = _install_job_listings(
            monkeypatch, [{"total_count": 1, "jobs": [_job(0, "build")]}]
        )

        assert len(list_run_jobs("o/r", "123", token="ghs_x")) == 1
        assert len(calls) == 1

    def test_unknown_run_refuses_instead_of_reporting_no_failures(self, monkeypatch):
        def _fake(request, timeout=None):
            raise _http_error(404, b"Not Found")

        monkeypatch.setattr(gh_rest_transport, "urlopen", _fake)

        with pytest.raises(RestNotFoundError) as exc_info:
            list_run_jobs("o/r", "404123", token="ghs_x")
        assert "404123" in str(exc_info.value)

    def test_unreadable_listing_refuses_instead_of_reporting_no_failures(
        self, monkeypatch
    ):
        _install_job_listings(monkeypatch, [{"total_count": 1, "jobs": "nope"}])

        with pytest.raises(RestTransportError) as exc_info:
            list_run_jobs("o/r", "123", token="ghs_x")
        assert "unreadable job listing" in str(exc_info.value)
