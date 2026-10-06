"""``failed-log`` subcommand logic: every failed job of the run, printed."""

from __future__ import annotations

import pytest

from yoke_core.domain import github_actions, github_actions_rest
from yoke_core.domain.gh_rest_transport import RestAuthError
from runtime.api.domain.test_github_actions_rest import _RESOLVED


@pytest.fixture
def _resolver_ok(monkeypatch):
    monkeypatch.setattr(
        github_actions_rest,
        "resolve_project_github_auth",
        lambda project, **kw: _RESOLVED,
    )


class TestFailedLog:
    """``failed-log`` reports every failed job of the run."""

    def _stub_collect(self, monkeypatch, payload):
        """Replace the production job collection with a fixed return."""
        from yoke_core.domain import github_actions_run_monitoring
        from yoke_core.domain.github_actions_failed_jobs import RunFailures

        def _fake(_repo, _run_id, *, token):
            if isinstance(payload, Exception):
                raise payload
            return RunFailures(failed=list(payload))

        monkeypatch.setattr(github_actions_run_monitoring, "collect_failed_jobs", _fake)

    @staticmethod
    def _job(name: str, body: str, job_id: str = "900"):
        from yoke_core.domain.github_actions_failed_jobs import (
            LOG_AVAILABLE,
            FailedJob,
        )

        return FailedJob(
            job_id=job_id,
            name=name,
            conclusion="failure",
            html_url=f"https://github.com/o/r/actions/runs/123/job/{job_id}",
            log_text=body,
            log_status=LOG_AVAILABLE,
            log_detail="",
        )

    def test_success_prints_the_failed_job(self, capsys, _resolver_ok, monkeypatch):
        log_text = "\n".join(f"line {i}" for i in range(10))
        self._stub_collect(monkeypatch, [self._job("build", log_text)])

        with pytest.raises(SystemExit) as exc_info:
            github_actions.failed_log_command(
                "o/r",
                "123",
                max_lines=50,
                project="yoke",
            )
        assert exc_info.value.code == 0
        assert "line 9" in capsys.readouterr().out

    def test_bounds_each_job_to_max_lines(self, capsys, _resolver_ok, monkeypatch):
        log_text = "\n".join(f"line {i}" for i in range(100))
        self._stub_collect(monkeypatch, [self._job("build", log_text)])

        with pytest.raises(SystemExit) as exc_info:
            github_actions.failed_log_command(
                "o/r",
                "456",
                max_lines=10,
                project="yoke",
            )
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "90 line(s) of this job's failure region trimmed" in out
        assert "line 89\n" not in out
        assert "line 90" in out
        assert "line 99" in out

    def test_rest_failure_exits_1(self, _resolver_ok, monkeypatch, capsys):
        from yoke_core.domain.gh_rest_transport import RestNotFoundError

        self._stub_collect(
            monkeypatch, RestNotFoundError("run 999 not found", status=404)
        )

        with pytest.raises(SystemExit) as exc_info:
            github_actions.failed_log_command(
                "o/r",
                "999",
                max_lines=50,
                project="yoke",
            )
        assert exc_info.value.code == 1
        assert "failed to fetch" in capsys.readouterr().err

    def test_auth_failure_exits_1(self, _resolver_ok, monkeypatch, capsys):
        self._stub_collect(
            monkeypatch, RestAuthError("HTTP 401: bad token", status=401)
        )

        with pytest.raises(SystemExit) as exc_info:
            github_actions.failed_log_command(
                "o/r",
                "111",
                max_lines=50,
                project="yoke",
            )
        assert exc_info.value.code == 1
        assert "GitHub auth failure" in capsys.readouterr().err

    def test_no_failed_jobs_reports_the_run_and_exits_0(
        self, _resolver_ok, monkeypatch, capsys
    ):
        self._stub_collect(monkeypatch, [])

        with pytest.raises(SystemExit) as exc_info:
            github_actions.failed_log_command(
                "o/r",
                "789",
                max_lines=50,
                project="yoke",
            )
        assert exc_info.value.code == 0
        assert "No failed jobs in run 789" in capsys.readouterr().out

    def test_every_failed_job_reaches_the_output(
        self, capsys, _resolver_ok, monkeypatch
    ):
        self._stub_collect(
            monkeypatch,
            [
                self._job("build", "build line 1\nbuild line 2", "901"),
                self._job("test", "test line", "902"),
            ],
        )

        with pytest.raises(SystemExit) as exc_info:
            github_actions.failed_log_command(
                "o/r",
                "555",
                max_lines=50,
                project="yoke",
            )
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "build line 1" in out
        assert "test line" in out
        assert "failed job 1/2" in out and "failed job 2/2" in out
