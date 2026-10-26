"""Focused --help teaching for the itemless environment-release path."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import pytest

from yoke_cli.transport.https import HttpsConnection

from yoke_cli.main import main as cli_main
from yoke_cli.commands.deployment_execute import deployment_runs_execute
from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_contracts.deployment_itemless_teaching import (
    INTERRUPTED_RUN_RECOVERY,
    ITEMLESS_RELEASE_RECIPE,
)


def _help(*argv: str) -> tuple[int, str, str]:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
            out = io.StringIO()
            err = io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = cli_main(list(argv))
            return rc, out.getvalue(), err.getvalue()


def _assert_itemless_recipe(text: str) -> None:
    # Shared constant must be the single source for the recipe body.
    assert ITEMLESS_RELEASE_RECIPE.strip() in text
    assert INTERRUPTED_RUN_RECOVERY.strip() in text


def test_resolve_target_help_teaches_verify_destination() -> None:
    rc, out, err = _help(
        "deployment-runs",
        "resolve-target",
        "--help",
    )
    assert rc == 0, err
    _assert_itemless_recipe(out)


def test_create_help_keeps_one_description_and_targets_the_recipe_read() -> None:
    rc, out, err = _help("deployment-runs", "create", "--help")
    assert rc == 0, err
    assert len(out) <= 5600
    recipe_rc, recipe, recipe_err = _help("deployment-runs", "resolve-target", "--help")
    assert recipe_rc == 0, recipe_err
    _assert_itemless_recipe(recipe)


def test_watch_deploy_help_teaches_itemless_release_path() -> None:
    rc, out, err = _help("watch", "deploy", "--help")
    assert rc == 0, err
    assert "--project-repo-path" in out
    _assert_itemless_recipe(out)


def test_execute_help_teaches_interrupted_run_redrive() -> None:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = deployment_runs_execute(["--help"])
    assert rc == 0, err.getvalue()
    text = out.getvalue()
    assert INTERRUPTED_RUN_RECOVERY.strip() in text


def _create_stderr(env: dict[str, str]) -> str:
    from yoke_contracts.api.function_call import (
        FunctionCallResponse,
    )

    def stub(*, function_id, **_kwargs) -> FunctionCallResponse:
        return FunctionCallResponse(
            success=True,
            function=function_id,
            version="v1",
            result={
                "target_environment_name": "prod",
                "run_id": "run-20260805-001",
                "status": "created",
                "idempotency_key": "stage-1",
                "replayed": False,
            },
        )

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session", **env}):
        with (
            patch("yoke_cli.commands._helpers.call_dispatcher", side_effect=stub),
            patch(
                "yoke_cli.commands.adapters.deployment_execution_authority."
                "call_dispatcher",
                side_effect=stub,
            ),
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                out = io.StringIO()
                err = io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    rc = cli_main(
                        [
                            "deployment-runs",
                            "create",
                            "yoke",
                            "yoke-hosted-stage-no-ci-gate",
                            "--idempotency-key",
                            "stage-1",
                        ]
                    )
    assert rc == 0, err.getvalue()
    assert "run id: run-20260805-001" in out.getvalue()
    return err.getvalue()


def test_create_post_note_points_at_watch_deploy() -> None:
    err = _create_stderr({})
    assert "watch deploy -- run-20260805-001" in err
    assert "deployment-runs execute" not in err
    assert "warning" not in err


@pytest.mark.parametrize(
    "host, expected",
    [
        ("control.example", "prod-db-admin"),
        ("stage.example", "prod"),
        (None, "<control-plane-env>"),
    ],
)
def test_create_note_names_only_proven_execution_authority(host, expected) -> None:
    authority = "yoke_cli.commands.adapters.deployment_execution_authority"
    run_read = {"return_value": {"project": "customer", "target_environment": "prod"}}
    if host is None:
        run_read = {"side_effect": RuntimeError("run unavailable")}
    with (
        patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=HttpsConnection(
                api_url="https://control.example/v1", token="token", env="prod"
            ),
        ),
        patch(f"{authority}._run", **run_read),
        patch(
            "yoke_cli.config.machine_config.load_config",
            return_value={
                "connections": {"prod-db-admin": {"transport": "local-postgres"}}
            },
        ),
        patch(
            "yoke_cli.commands.pulumi_stack_config_loader."
            "load_project_renderer_settings_snapshot",
            return_value={
                "renderer_settings": {
                    "environments": [
                        {"name": "prod", "settings": {"hosts": {"api": host}}}
                    ]
                }
            },
        ),
    ):
        err = _create_stderr({ENV_OVERRIDE: "prod"})
    assert f"yoke --env {expected} watch deploy -- run-20260805-001" in err
