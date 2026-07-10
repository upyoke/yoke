"""REST-backed ``check-ci`` command behavior."""

# Ruff sees fixture parameters as redefinitions of the deliberately imported
# pytest fixture below; the shared fixture must remain in this module namespace.
# ruff: noqa: F811

from __future__ import annotations

from typing import Any, Dict

import pytest

from runtime.api.domain.test_github_actions_rest import (
    _fake_urls,
    _raise_error,
    _resolver_ok as _resolver_ok,
)
from yoke_core.domain import github_actions, github_actions_rest
from yoke_core.domain import github_actions_run_monitoring
from yoke_core.domain.project_github_auth import (
    MissingAppCredentials,
    MissingCapability,
)


def _run_payload(**fields: Any) -> Dict[str, Any]:
    base = {
        "id": 42,
        "status": "queued",
        "conclusion": None,
        "html_url": "https://x",
    }
    base.update(fields)
    return {"workflow_runs": [base]}


class TestCheckCi:
    def test_green(self, _resolver_ok, monkeypatch):
        with _fake_urls(
            monkeypatch,
            [_run_payload(status="completed", conclusion="success")],
        ):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_check_ci("o/r", "ci.yml", project="yoke")
            assert exc_info.value.code == 0

    def test_red(self, _resolver_ok, monkeypatch):
        with _fake_urls(
            monkeypatch,
            [_run_payload(status="completed", conclusion="failure")],
        ):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_check_ci("o/r", "ci.yml", project="yoke")
            assert exc_info.value.code == 1

    def test_running_no_wait(self, _resolver_ok, monkeypatch):
        with _fake_urls(
            monkeypatch,
            [_run_payload(status="in_progress", conclusion=None)],
        ):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_check_ci(
                    "o/r", "ci.yml", wait=False, project="yoke",
                )
            assert exc_info.value.code == 2

    def test_queued_classified_as_running(self, _resolver_ok, monkeypatch, capsys):
        """Operator decision: ``queued`` collapses into the running exit code."""
        with _fake_urls(
            monkeypatch,
            [_run_payload(status="queued", conclusion=None)],
        ):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_check_ci(
                    "o/r", "ci.yml", wait=False, project="yoke",
                )
            assert exc_info.value.code == 2
        assert "running:queued" in capsys.readouterr().out

    def test_no_runs(self, _resolver_ok, monkeypatch):
        with _fake_urls(monkeypatch, [{"workflow_runs": []}]):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_check_ci("o/r", "ci.yml", project="yoke")
            assert exc_info.value.code == 0

    def test_wait_polls_until_delayed_run_appears(
        self, monkeypatch, capsys,
    ):
        runs = iter([
            None,
            {
                "id": 42,
                "status": "completed",
                "conclusion": "success",
                "html_url": "https://github.example/o/r/actions/runs/42",
            },
        ])
        clock = iter([0.0, 0.0])
        sleeps = []

        with pytest.raises(SystemExit) as exc_info:
            github_actions_run_monitoring.check_ci_command(
                "o/r",
                "ci.yml",
                branch="main",
                wait=True,
                timeout_sec=600,
                check_auth=lambda: None,
                get_latest_run=lambda: next(runs),
                now=lambda: next(clock),
                sleep=sleeps.append,
            )

        assert exc_info.value.code == 0
        assert sleeps == [15]
        output = capsys.readouterr()
        assert "has not appeared yet" in output.err
        assert "passed|42|" in output.out

    def test_wait_accepts_no_runs_only_after_appearance_timeout(
        self, capsys,
    ):
        clock = iter([0.0, 0.0, 90.0])
        sleeps = []

        with pytest.raises(SystemExit) as exc_info:
            github_actions_run_monitoring.check_ci_command(
                "o/r",
                "ci.yml",
                branch="main",
                wait=True,
                timeout_sec=600,
                check_auth=lambda: None,
                get_latest_run=lambda: None,
                now=lambda: next(clock),
                sleep=sleeps.append,
            )

        assert exc_info.value.code == 0
        assert sleeps == [15]
        assert capsys.readouterr().out.strip() == "no_runs"

    def test_malformed_response_fails_closed(
        self, _resolver_ok, monkeypatch, capsys,
    ):
        with _fake_urls(monkeypatch, [{}]):
            with pytest.raises(SystemExit) as exc_info:
                github_actions.cmd_check_ci(
                    "o/r", "ci.yml", project="yoke",
                )
            assert exc_info.value.code == 1
        assert "omitted workflow_runs" in capsys.readouterr().err

    def test_missing_app_credentials_exit_4(self, monkeypatch, capsys):
        """A control-plane credential resolution failure exits with code 4."""
        monkeypatch.setattr(
            github_actions_rest, "resolve_project_github_auth",
            _raise_error(MissingAppCredentials),
        )
        with pytest.raises(SystemExit) as exc_info:
            github_actions.cmd_check_ci("o/r", "ci.yml", project="yoke")
        assert exc_info.value.code == 4
        assert "missing_app_credentials" in capsys.readouterr().err

    def test_resolver_capability_exits_4(self, monkeypatch, capsys):
        monkeypatch.setattr(
            github_actions_rest, "resolve_project_github_auth",
            _raise_error(MissingCapability),
        )
        with pytest.raises(SystemExit) as exc_info:
            github_actions.cmd_check_ci("o/r", "ci.yml", project="yoke")
        assert exc_info.value.code == 4
        assert "missing_capability" in capsys.readouterr().err
