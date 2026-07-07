"""Unit tests for the deploy-QA subprocess dispatch helpers.

Focus: the failure-surfacing contract. The deploy pipeline runs these
helpers in-process and treats an empty return as failure; the underlying
subprocess's stderr and return code must be re-emitted to this process's
stderr (so they land in the deploy log) instead of being captured and
dropped. A timeout must degrade to an empty return, not raise.
"""

from __future__ import annotations

import subprocess

import pytest

from yoke_core.domain import deploy_qa_stage_helpers as helpers


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_failure_reemits_stderr_and_returns_empty(monkeypatch, capsys):
    def fake_run(cmd, **kwargs):
        return _FakeCompleted(returncode=1, stdout="", stderr="psycopg.OperationalError: boom")

    monkeypatch.setattr(helpers.subprocess, "run", fake_run)

    out = helpers.dispatch_db_router("qa", "requirement-add", "--qa-kind", "smoke")

    assert out == ""
    err = capsys.readouterr().err
    assert "dispatch failure" in err
    assert "exited 1" in err
    assert "psycopg.OperationalError: boom" in err


def test_failure_without_stderr_is_still_reported(monkeypatch, capsys):
    def fake_run(cmd, **kwargs):
        return _FakeCompleted(returncode=2, stdout="", stderr="")

    monkeypatch.setattr(helpers.subprocess, "run", fake_run)

    out = helpers.dispatch_flow_domain("stages", "flow-x")

    assert out == ""
    err = capsys.readouterr().err
    assert "dispatch failure" in err
    assert "no stderr captured" in err


def test_success_returns_stripped_stdout_silently(monkeypatch, capsys):
    def fake_run(cmd, **kwargs):
        return _FakeCompleted(returncode=0, stdout="  7124\n", stderr="")

    monkeypatch.setattr(helpers.subprocess, "run", fake_run)

    out = helpers.dispatch_db_router("qa", "requirement-add")

    assert out == "7124"
    assert capsys.readouterr().err == ""


def test_timeout_degrades_to_empty_return(monkeypatch, capsys):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=helpers.DISPATCH_TIMEOUT_S)

    monkeypatch.setattr(helpers.subprocess, "run", fake_run)

    out = helpers.dispatch_db_router("qa", "requirement-add")

    assert out == ""
    err = capsys.readouterr().err
    assert "dispatch timeout" in err
    assert str(helpers.DISPATCH_TIMEOUT_S) in err
