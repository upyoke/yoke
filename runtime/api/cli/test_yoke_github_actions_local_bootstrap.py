"""Attended local bootstrap uses the typed durable workflow handler."""

from __future__ import annotations

import io
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from yoke_cli.commands.adapters import github_actions_workflow as workflow_adapter
from yoke_cli.main import main as cli_main
from yoke_contracts.github_workflow_dispatch import (
    GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV,
)
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain.github_actions_local_authority import dispatch as local_dispatch
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def test_local_bootstrap_routes_through_durable_typed_dispatch(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(workflow_adapter, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        "yoke_cli.config.machine_config.github_config", lambda: {},
    )
    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        lambda *args, **kwargs: ProjectGithubAuth(
            project="yoke", repo="upyoke/platform", token="ghs_test",
        ),
    )
    posts = []

    def _post(path, *, body, token, max_attempts):
        posts.append((path, body, token, max_attempts))
        return {"workflow_run_id": 731}

    monkeypatch.setattr("yoke_core.domain.github_actions_rest.rest_post", _post)
    argv = [
        "github-actions", "trigger", "upyoke/platform", "deploy.yml",
        "--ref", "main", "--request-id", "local-bootstrap-1",
        "--correlation-input", "yoke_dispatch_id", "--project", "yoke",
    ]
    with init_test_db(tmp_path) as db_path, patch.dict(
        os.environ,
        {
            GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV: "1",
            "GITHUB_ACTIONS": "",
            "YOKE_SESSION_ID": "",
        },
        clear=False,
    ), redirect_stdout(io.StringIO()) as stdout, redirect_stderr(
        io.StringIO()
    ) as stderr:
        rc = cli_main(argv)
        with connect_test_db(db_path) as conn:
            row = conn.execute(
                "SELECT state, workflow_run_id FROM "
                "github_workflow_dispatch_intents "
                "WHERE request_id = 'local-bootstrap-1'"
            ).fetchone()

    assert rc == 0, stderr.getvalue()
    assert stdout.getvalue() == "731\n"
    assert row == ("completed", "731")
    assert posts[0][1]["inputs"]["yoke_dispatch_id"].startswith("yd-")
    assert posts[0][3] == 1


def test_local_authority_does_not_expose_generic_prod_functions() -> None:
    request = FunctionCallRequest(
        function="items.list.run",
        actor=ActorContext(actor_id="2", session_id=""),
        target=TargetRef(kind="global"),
    )
    with patch.dict(
        os.environ,
        {GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV: "1", "GITHUB_ACTIONS": ""},
    ):
        response = local_dispatch(request)
    assert response.success is False
    assert response.error.code == "local_github_authority_denied"
    assert "outside" in response.error.message


def test_local_authority_is_unavailable_inside_github_actions() -> None:
    request = FunctionCallRequest(
        function="github_actions.workflow.dispatch",
        actor=ActorContext(actor_id="2", session_id=""),
        target=TargetRef(kind="global"),
        payload={"project": "yoke"},
    )
    with patch.dict(
        os.environ,
        {
            GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV: "1",
            "GITHUB_ACTIONS": "true",
        },
    ):
        response = local_dispatch(request)
    assert response.success is False
    assert response.error.code == "local_github_authority_denied"
    assert "inside GitHub Actions" in response.error.message


def test_adapter_refuses_implicit_local_authority(monkeypatch) -> None:
    monkeypatch.delenv(GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV, raising=False)
    monkeypatch.setattr(workflow_adapter, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection", lambda: None,
    )
    argv = [
        "github-actions", "trigger", "upyoke/platform", "deploy.yml",
        "--request-id", "implicit-local", "--correlation-input",
        "yoke_dispatch_id", "--project", "yoke",
    ]
    with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(
        io.StringIO()
    ) as stderr:
        rc = cli_main(argv)
    assert rc == 4
    assert stdout.getvalue() == ""
    assert "github_actions_authority_required" in stderr.getvalue()
