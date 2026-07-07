"""Subcommand-logic tests for github_actions.py.

REST helper tests + ``check-ci`` REST coverage live in the sibling
``test_github_actions_rest.py`` module to keep both files under the
authored-file line cap.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import github_actions, github_actions_rest
from yoke_core.domain.gh_rest_transport import RestAuthError
from yoke_core.domain.project_github_auth import (
    MissingCapability,
    MissingToken,
    ProjectGithubAuth,
)
from runtime.api.domain.test_github_actions_rest import (
    _RESOLVED,
    _fake_urls,
    _raise_error,
)


@pytest.fixture
def _resolver_ok(monkeypatch):
    monkeypatch.setattr(
        github_actions_rest, "resolve_project_github_auth",
        lambda project, **kw: _RESOLVED,
    )


class TestPoll:
    def test_success(self, _resolver_ok, monkeypatch):
        with _fake_urls(
            monkeypatch,
            [{"status": "completed", "conclusion": "success"}],
        ):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_poll("o/r", "123")
            assert exc_info.value.code == 0

    def test_failed(self, _resolver_ok, monkeypatch):
        with _fake_urls(
            monkeypatch,
            [{"status": "completed", "conclusion": "failure"}],
        ):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_poll("o/r", "123")
            assert exc_info.value.code == 1

    def test_waiting(self, _resolver_ok, monkeypatch):
        with _fake_urls(
            monkeypatch,
            [{"status": "queued", "conclusion": None}],
        ):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_poll("o/r", "123")
            assert exc_info.value.code == 2

    def test_in_progress(self, _resolver_ok, monkeypatch):
        with _fake_urls(
            monkeypatch,
            [{"status": "in_progress", "conclusion": None}],
        ):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_poll("o/r", "123")
            assert exc_info.value.code == 3

    def test_resolver_error_exits_4(self, monkeypatch, capsys):
        monkeypatch.setattr(
            github_actions_rest, "resolve_project_github_auth",
            _raise_error(MissingToken),
        )
        with pytest.raises(SystemExit) as exc_info:
            github_actions.cmd_poll("o/r", "123")
        assert exc_info.value.code == 4
        assert "missing_token" in capsys.readouterr().err


class TestWaitRun:
    def test_success_after_waiting(self, monkeypatch, _resolver_ok):
        responses = [
            {"status": "queued", "conclusion": None},
            {"status": "in_progress", "conclusion": None},
            {"status": "completed", "conclusion": "success"},
        ]
        sleeps: list[int] = []
        monkeypatch.setattr(github_actions.time, "sleep", lambda secs: sleeps.append(secs))
        monotonic_values = iter([0.0, 0.0, 5.0])
        monkeypatch.setattr(github_actions.time, "monotonic", lambda: next(monotonic_values))

        with _fake_urls(monkeypatch, responses):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_wait_run("o/r", "123", timeout_sec=1800)
            assert exc_info.value.code == 0

        assert sleeps == [5, 10]

    def test_failure_exits_1(self, _resolver_ok, monkeypatch):
        with _fake_urls(
            monkeypatch,
            [{"status": "completed", "conclusion": "failure"}],
        ):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_wait_run("o/r", "123", timeout_sec=1800)
            assert exc_info.value.code == 1

    def test_timeout_exits_3(self, monkeypatch, _resolver_ok):
        responses = [
            {"status": "queued", "conclusion": None},
            {"status": "in_progress", "conclusion": None},
        ]
        sleeps: list[int] = []
        monkeypatch.setattr(github_actions.time, "sleep", lambda secs: sleeps.append(secs))
        monotonic_values = iter([0.0, 0.0, 5.0])
        monkeypatch.setattr(github_actions.time, "monotonic", lambda: next(monotonic_values))

        with _fake_urls(monkeypatch, responses):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_wait_run("o/r", "123", timeout_sec=5)
            assert exc_info.value.code == 3

        assert sleeps == [5]


class TestFindRun:
    def test_found(self, _resolver_ok, monkeypatch):
        with _fake_urls(monkeypatch, [{"workflow_runs": [{"id": 999}]}]):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_find_run("o/r", "ci.yml", "abc123")
            assert exc_info.value.code == 0

    def test_not_found(self, _resolver_ok, monkeypatch):
        with _fake_urls(monkeypatch, [{"workflow_runs": []}]):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_find_run("o/r", "ci.yml", "abc123")
            assert exc_info.value.code == 1


class TestFailedLog:
    """``failed-log`` dispatches through the ZIP REST path."""

    def _stub_fetch(self, monkeypatch, payload):
        """Replace the production ``fetch_failed_log`` with a fixed return."""
        from yoke_core.domain import github_actions_logs

        def _fake(_repo, _run_id, *, token):
            if isinstance(payload, Exception):
                raise payload
            return payload

        monkeypatch.setattr(github_actions_logs, "fetch_failed_log", _fake)

    def test_success_returns_log_tail(self, capsys, _resolver_ok, monkeypatch):
        log_text = "\n".join(f"line {i}" for i in range(10))
        self._stub_fetch(monkeypatch, {"build": log_text})

        with pytest.raises(SystemExit) as exc_info:
            github_actions.cmd_failed_log("o/r", "123")
        assert exc_info.value.code == 0
        assert "line 9" in capsys.readouterr().out

    def test_truncates_to_tail_lines(self, capsys, _resolver_ok, monkeypatch):
        log_text = "\n".join(f"line {i}" for i in range(100))
        self._stub_fetch(monkeypatch, {"build": log_text})

        with pytest.raises(SystemExit) as exc_info:
            github_actions.cmd_failed_log("o/r", "456", tail_lines=10)
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "showing last 10 lines" in out
        assert "line 89" not in out
        assert "line 90" in out
        assert "line 99" in out

    def test_rest_failure_exits_1(self, _resolver_ok, monkeypatch, capsys):
        from yoke_core.domain.gh_rest_transport import RestNotFoundError

        self._stub_fetch(monkeypatch, RestNotFoundError("run 999 not found", status=404))

        with pytest.raises(SystemExit) as exc_info:
            github_actions.cmd_failed_log("o/r", "999")
        assert exc_info.value.code == 1
        assert "failed to fetch" in capsys.readouterr().err

    def test_auth_failure_exits_1(self, _resolver_ok, monkeypatch, capsys):
        self._stub_fetch(monkeypatch, RestAuthError("HTTP 401: bad token", status=401))

        with pytest.raises(SystemExit) as exc_info:
            github_actions.cmd_failed_log("o/r", "111")
        assert exc_info.value.code == 1
        assert "GitHub auth failure" in capsys.readouterr().err

    def test_empty_log_exits_1(self, _resolver_ok, monkeypatch, capsys):
        self._stub_fetch(monkeypatch, {})

        with pytest.raises(SystemExit) as exc_info:
            github_actions.cmd_failed_log("o/r", "789")
        assert exc_info.value.code == 1
        assert "no failed-step" in capsys.readouterr().err

    def test_multiple_jobs_joined(self, capsys, _resolver_ok, monkeypatch):
        self._stub_fetch(
            monkeypatch,
            {"build": "build line 1\nbuild line 2", "test": "test line"},
        )

        with pytest.raises(SystemExit) as exc_info:
            github_actions.cmd_failed_log("o/r", "555")
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        # Jobs ordered alphabetically; both present.
        assert "build line 1" in out
        assert "test line" in out
