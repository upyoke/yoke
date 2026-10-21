"""Focused --help teaching for the itemless environment-release path."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_cli.commands.deployment_execute import deployment_runs_execute
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


def test_create_post_note_points_at_watch_deploy() -> None:
    from yoke_contracts.api.function_call import (
        FunctionCallRequest,
        FunctionCallResponse,
    )

    def stub(request: FunctionCallRequest) -> FunctionCallResponse:
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={
                "run_id": "run-20260805-001",
                "status": "created",
                "idempotency_key": "stage-1",
                "replayed": False,
            },
        )

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=stub,
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
    assert rc == 0
    assert "run id: run-20260805-001" in out.getvalue()
    assert "watch deploy -- run-20260805-001" in err.getvalue()
    assert "deployment-runs execute" not in err.getvalue()
    assert "warning" not in err.getvalue()
