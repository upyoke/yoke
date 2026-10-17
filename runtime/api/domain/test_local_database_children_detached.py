"""Local-database children never inherit setup's terminal.

Setup's Apply starts the local universe database while the wizard owns the
terminal; initdb, pg_ctl, psql and pg_dump must run without it.
"""

from __future__ import annotations

import subprocess

from yoke_core.domain import postgres_cluster


def test_cluster_commands_run_detached_from_the_terminal(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    postgres_cluster._run(["pg_ctl", "status"])
    assert calls[0]["stdin"] is subprocess.DEVNULL
    assert calls[0]["start_new_session"] is True
    assert calls[0]["capture_output"] is True
