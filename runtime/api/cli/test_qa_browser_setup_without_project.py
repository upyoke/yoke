"""``yoke qa browser setup`` before any project: machine runtime only, no daemon."""

from __future__ import annotations

import json

import pytest

from yoke_cli.commands import qa_browser_lifecycle, qa_browser_machine_runtime
from yoke_cli.config import project_selection


@pytest.fixture
def no_project(monkeypatch, tmp_path):
    monkeypatch.delenv("YOKE_PROJECT", raising=False)
    monkeypatch.setattr(
        project_selection, "default_project_for_directory", lambda _p: None
    )
    monkeypatch.setattr(
        "yoke_cli.config.project_selection.missing_project_context",
        lambda **_k: pytest.fail("no project must not ask the server for one"),
    )
    monkeypatch.setattr(
        "yoke_harness.browser_runtime_home.ensure_materialized", lambda: tmp_path
    )
    monkeypatch.setattr(qa_browser_lifecycle, "_ensure_node_toolchain", lambda **_k: [])
    monkeypatch.setattr(
        "yoke_harness.browser_client.daemon_start",
        lambda **_k: pytest.fail("no project must not start a daemon"),
    )


def test_setup_installs_the_machine_runtime_and_names_the_next_step(
    no_project, monkeypatch, capsys
):
    installed = []
    monkeypatch.setattr(
        "yoke_harness.browser_setup.ensure_browser_runtime",
        lambda *_a, **_k: installed.append(True),
    )

    assert qa_browser_lifecycle.qa_browser_setup(["--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert installed == [True]
    assert payload["ok"] is True
    assert payload["daemon"] == {
        "status": "not_started",
        "detail": qa_browser_machine_runtime.NO_PROJECT_DETAIL,
    }


def test_a_machine_runtime_failure_keeps_its_named_recovery(
    no_project, monkeypatch, capsys
):
    def refuse(*_a, **_k):
        raise RuntimeError("browser_apparmor_setup_failed: no sudo. Allow sudo.")

    monkeypatch.setattr("yoke_harness.browser_setup.ensure_browser_runtime", refuse)

    assert qa_browser_lifecycle.qa_browser_setup(["--json"]) == 2

    failure = json.loads(capsys.readouterr().out)
    assert failure == {
        "ok": False,
        "error": "browser_apparmor_setup_failed: no sudo. Allow sudo.",
    }
