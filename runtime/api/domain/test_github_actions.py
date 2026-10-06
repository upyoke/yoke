"""Subcommand-logic tests for github_actions.py.

REST helper tests + ``check-ci`` REST coverage live in the sibling
``test_github_actions_rest.py`` module to keep both files under the
authored-file line cap.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import github_actions, github_actions_rest
from yoke_core.domain.project_github_auth import (
    MissingAppCredentials,
)
from runtime.api.domain.test_github_actions_rest import (
    _RESOLVED,
    _fake_urls,
    _raise_error,
)


@pytest.fixture
def _resolver_ok(monkeypatch):
    monkeypatch.setattr(
        github_actions_rest,
        "resolve_project_github_auth",
        lambda project, **kw: _RESOLVED,
    )


class TestPoll:
    def test_success(self, _resolver_ok, monkeypatch):
        with _fake_urls(
            monkeypatch,
            [{"status": "completed", "conclusion": "success"}],
        ):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_poll("o/r", "123", project="yoke")
            assert exc_info.value.code == 0

    def test_failed(self, _resolver_ok, monkeypatch):
        with _fake_urls(
            monkeypatch,
            [{"status": "completed", "conclusion": "failure"}],
        ):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_poll("o/r", "123", project="yoke")
            assert exc_info.value.code == 1

    def test_waiting(self, _resolver_ok, monkeypatch):
        with _fake_urls(
            monkeypatch,
            [{"status": "queued", "conclusion": None}],
        ):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_poll("o/r", "123", project="yoke")
            assert exc_info.value.code == 2

    def test_in_progress(self, _resolver_ok, monkeypatch):
        with _fake_urls(
            monkeypatch,
            [{"status": "in_progress", "conclusion": None}],
        ):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_poll("o/r", "123", project="yoke")
            assert exc_info.value.code == 3

    def test_missing_app_credentials_exit_4(self, monkeypatch, capsys):
        monkeypatch.setattr(
            github_actions_rest,
            "resolve_project_github_auth",
            _raise_error(MissingAppCredentials),
        )
        with pytest.raises(SystemExit) as exc_info:
            github_actions.cmd_poll("o/r", "123", project="yoke")
        assert exc_info.value.code == 4
        assert "missing_app_credentials" in capsys.readouterr().err


class TestWaitRun:
    def test_success_after_waiting(self, monkeypatch, _resolver_ok):
        responses = [
            {"status": "queued", "conclusion": None},
            {"status": "in_progress", "conclusion": None},
            {"status": "completed", "conclusion": "success"},
        ]
        sleeps: list[int] = []
        monkeypatch.setattr(
            github_actions.time, "sleep", lambda secs: sleeps.append(secs)
        )
        monotonic_values = iter([0.0, 0.0, 60.0])
        monkeypatch.setattr(
            github_actions.time, "monotonic", lambda: next(monotonic_values)
        )

        with _fake_urls(monkeypatch, responses):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_wait_run(
                    "o/r",
                    "123",
                    timeout_sec=1800,
                    project="yoke",
                )
            assert exc_info.value.code == 0

        # A run waited on by id has no known duration floor, so every read
        # is one minimum interval after the last.
        assert sleeps == [60.0, 60.0]

    def test_failure_exits_1(self, _resolver_ok, monkeypatch):
        with _fake_urls(
            monkeypatch,
            [{"status": "completed", "conclusion": "failure"}],
        ):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_wait_run(
                    "o/r",
                    "123",
                    timeout_sec=1800,
                    project="yoke",
                )
            assert exc_info.value.code == 1

    def test_timeout_exits_3(self, monkeypatch, _resolver_ok):
        responses = [
            {"status": "queued", "conclusion": None},
            {"status": "in_progress", "conclusion": None},
        ]
        sleeps: list[int] = []
        monkeypatch.setattr(
            github_actions.time, "sleep", lambda secs: sleeps.append(secs)
        )
        monotonic_values = iter([0.0, 0.0, 5.0])
        monkeypatch.setattr(
            github_actions.time, "monotonic", lambda: next(monotonic_values)
        )

        with _fake_urls(monkeypatch, responses):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_wait_run(
                    "o/r",
                    "123",
                    timeout_sec=5,
                    project="yoke",
                )
            assert exc_info.value.code == 3

        # The budget is shorter than one interval, so the wait sleeps once
        # and reports the timeout at its next read rather than reading early.
        assert sleeps == [60.0]


class TestFindRun:
    def test_found(self, _resolver_ok, monkeypatch):
        with _fake_urls(monkeypatch, [{"workflow_runs": [{"id": 999}]}]):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_find_run(
                    "o/r",
                    "ci.yml",
                    "abc123",
                    project="yoke",
                )
            assert exc_info.value.code == 0

    def test_not_found(self, _resolver_ok, monkeypatch):
        with _fake_urls(monkeypatch, [{"workflow_runs": []}]):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_find_run(
                    "o/r",
                    "ci.yml",
                    "abc123",
                    project="yoke",
                )
            assert exc_info.value.code == 1

    @pytest.mark.parametrize(
        "payload",
        [None, {}, {"workflow_runs": {}}, {"workflow_runs": [{}]}],
    )
    def test_malformed_response_fails_instead_of_reporting_not_found(
        self, payload, _resolver_ok, monkeypatch, capsys
    ):
        with _fake_urls(monkeypatch, [payload]):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_find_run(
                    "o/r",
                    "ci.yml",
                    "abc123",
                    project="yoke",
                )
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Error:" in captured.err


class TestJobsCount:
    def test_count(self, _resolver_ok, monkeypatch, capsys):
        with _fake_urls(monkeypatch, [{"total_count": 3}]):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_jobs_count("o/r", "123", project="yoke")
        assert exc_info.value.code == 0
        assert capsys.readouterr().out == "3\n"

    @pytest.mark.parametrize(
        "payload",
        [None, {}, {"total_count": "3"}, {"total_count": True}, {"total_count": -1}],
    )
    def test_malformed_count_fails_instead_of_reporting_zero(
        self, payload, _resolver_ok, monkeypatch, capsys
    ):
        with _fake_urls(monkeypatch, [payload]):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_jobs_count("o/r", "123", project="yoke")
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Error:" in captured.err
