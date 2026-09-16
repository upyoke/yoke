"""Regressions for reading every failed job of one run.

A sharded run fails in several jobs at once. These cover that each of
them is collected with its own log text, that the job inventory follows
provider pagination, and that a job whose log GitHub will not hand over
carries a named reason rather than vanishing. Rendering is covered by
``test_github_actions_failed_job_report.py``.
"""

from __future__ import annotations

import io
import json
import urllib.error
import zipfile
from typing import Any, Dict, List

import pytest

from yoke_core.domain import gh_rest_transport, github_actions_logs
from yoke_core.domain.gh_rest_transport import RestNotFoundError, RestTransportError
from yoke_core.domain.github_actions_failed_jobs import (
    JOBS_PAGE_SIZE,
    LOG_AVAILABLE,
    LOG_EXPIRED_OR_MISSING,
    LOG_PERMISSION_DENIED,
    collect_failed_jobs,
    list_run_jobs,
)


SHARD_NAMES = (
    "test-shard (3.10, 6)",
    "test-shard (3.10, 7)",
    "test-shard (3.13, 6)",
    "test-shard (3.13, 7)",
)


def _job(index: int, name: str, conclusion: str = "failure") -> Dict[str, Any]:
    return {
        "id": 900 + index,
        "name": name,
        "conclusion": conclusion,
        "html_url": f"https://github.com/o/r/actions/runs/123/job/{900 + index}",
    }


def _zip_of(entries: Dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    return buf.getvalue()


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
    """Answer the archive / per-job log reads with *responses*, in order."""
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
    def test_every_failed_shard_is_collected_with_its_own_log(self, monkeypatch):
        _install_job_listings(
            monkeypatch,
            [{"total_count": 4, "jobs": [_job(i, n) for i, n in enumerate(SHARD_NAMES)]}],
        )
        _install_log_responses(
            monkeypatch,
            [
                _zip_of(
                    {
                        f"{i}_{name}.txt": f"FAILED signature {i}"
                        for i, name in enumerate(SHARD_NAMES)
                    }
                )
            ],
        )

        jobs = collect_failed_jobs("o/r", "123", token="ghs_x")

        assert [job.name for job in jobs] == list(SHARD_NAMES)
        assert [job.log_text for job in jobs] == [
            f"FAILED signature {i}" for i in range(4)
        ]
        assert {job.log_status for job in jobs} == {LOG_AVAILABLE}

    def test_successful_jobs_are_not_collected(self, monkeypatch):
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
        _install_log_responses(monkeypatch, [_zip_of({"0_build.txt": "boom"})])

        jobs = collect_failed_jobs("o/r", "123", token="ghs_x")

        assert [job.name for job in jobs] == ["build"]

    def test_run_with_no_failures_collects_nothing_without_fetching_logs(
        self, monkeypatch
    ):
        _install_job_listings(
            monkeypatch,
            [{"total_count": 1, "jobs": [_job(0, "build", conclusion="success")]}],
        )
        log_calls = _install_log_responses(monkeypatch, [])

        assert collect_failed_jobs("o/r", "123", token="ghs_x") == []
        assert log_calls == []

    def test_job_missing_from_the_archive_is_read_by_job_id(self, monkeypatch):
        _install_job_listings(
            monkeypatch,
            [{"total_count": 2, "jobs": [_job(0, "build"), _job(1, "test")]}],
        )
        calls = _install_log_responses(
            monkeypatch,
            [_zip_of({"0_build.txt": "build boom"}), b"test boom\n"],
        )

        jobs = {job.name: job for job in collect_failed_jobs("o/r", "1", token="ghs_x")}

        assert jobs["test"].log_text == "test boom\n"
        assert jobs["test"].log_status == LOG_AVAILABLE
        assert any("/actions/jobs/901/logs" in call for call in calls)

    def test_expired_job_log_is_reported_not_dropped(self, monkeypatch):
        _install_job_listings(
            monkeypatch,
            [{"total_count": 2, "jobs": [_job(0, "build"), _job(1, "test")]}],
        )
        _install_log_responses(
            monkeypatch,
            [_zip_of({"0_build.txt": "build boom"}), _http_error(404)],
        )

        jobs = {job.name: job for job in collect_failed_jobs("o/r", "1", token="ghs_x")}

        assert set(jobs) == {"build", "test"}
        assert jobs["test"].log_status == LOG_EXPIRED_OR_MISSING
        assert "expire" in jobs["test"].log_detail

    def test_permission_denied_job_log_is_reported_not_dropped(self, monkeypatch):
        _install_job_listings(
            monkeypatch,
            [{"total_count": 1, "jobs": [_job(0, "build")]}],
        )
        _install_log_responses(
            monkeypatch,
            [_zip_of({}), _http_error(403, b"forbidden")],
        )

        [job] = collect_failed_jobs("o/r", "1", token="ghs_x")

        assert job.log_status == LOG_PERMISSION_DENIED
        assert "Actions read" in job.log_detail

    def test_refused_archive_still_reports_every_job_from_its_own_log(
        self, monkeypatch
    ):
        """A 403 on the whole-run archive must not cost the job inventory."""
        _install_job_listings(
            monkeypatch,
            [{"total_count": 2, "jobs": [_job(0, "build"), _job(1, "test")]}],
        )
        _install_log_responses(
            monkeypatch,
            [_http_error(403, b"forbidden"), b"build boom\n", b"test boom\n"],
        )

        jobs = {job.name: job for job in collect_failed_jobs("o/r", "1", token="ghs_x")}

        assert set(jobs) == {"build", "test"}
        assert jobs["build"].log_text == "build boom\n"
        assert jobs["test"].log_text == "test boom\n"
        assert {job.log_status for job in jobs.values()} == {LOG_AVAILABLE}

    def test_unreachable_archive_still_reports_every_job_by_name_and_reason(
        self, monkeypatch
    ):
        """Archive and per-job logs both refused: name each job, not one error."""
        _install_job_listings(
            monkeypatch,
            [{"total_count": 2, "jobs": [_job(0, "build"), _job(1, "test")]}],
        )
        _install_log_responses(
            monkeypatch,
            [
                _http_error(500, b"upstream"),
                _http_error(500, b"upstream"),
                _http_error(500, b"upstream"),
                _http_error(403, b"forbidden"),
                _http_error(403, b"forbidden"),
            ],
        )

        jobs = {job.name: job for job in collect_failed_jobs("o/r", "1", token="ghs_x")}

        assert set(jobs) == {"build", "test"}
        assert {job.log_status for job in jobs.values()} == {LOG_PERMISSION_DENIED}
        assert all("Actions read" in job.log_detail for job in jobs.values())

    def test_missing_archive_falls_back_to_every_job_by_id(self, monkeypatch):
        _install_job_listings(
            monkeypatch,
            [{"total_count": 2, "jobs": [_job(0, "build"), _job(1, "test")]}],
        )
        _install_log_responses(
            monkeypatch, [_http_error(404), b"build boom\n", b"test boom\n"]
        )

        jobs = {job.name: job for job in collect_failed_jobs("o/r", "1", token="ghs_x")}

        assert jobs["build"].log_text == "build boom\n"
        assert jobs["test"].log_text == "test boom\n"


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
