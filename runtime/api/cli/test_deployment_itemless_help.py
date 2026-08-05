"""Focused --help teaching for the itemless environment-release path."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_core.domain.deployment_itemless_teaching import (
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
    assert "Itemless environment release" in text
    assert "resolve-target-env PROJECT FLOW" in text
    assert "Verify TARGET_ENV is the deploy destination" in text
    assert "--project-repo-path /path/to/checkout" in text
    assert "--source-ref origin/main" in text
    assert "watch deploy --" in text
    assert "CONTROL-PLANE-db-admin" in text
    # Shared constant must be the single source for the recipe body.
    assert ITEMLESS_RELEASE_RECIPE.strip() in text


def test_resolve_target_env_help_teaches_verify_destination() -> None:
    rc, out, err = _help(
        "deployment-runs", "resolve-target-env", "--help",
    )
    assert rc == 0, err
    assert "environment being deployed TO" in out
    assert "not the control-plane connection name" in out
    _assert_itemless_recipe(out)


def test_create_help_teaches_itemless_release_recipe() -> None:
    rc, out, err = _help("deployment-runs", "create", "--help")
    assert rc == 0, err
    assert "yoke watch deploy" in out
    assert "zero-member environment deployment run" in out
    _assert_itemless_recipe(out)


def test_deployment_runs_group_help_includes_itemless_recipe() -> None:
    rc, out, err = _help("deployment-runs", "--help")
    assert rc == 0, err
    _assert_itemless_recipe(out)


def test_watch_deploy_help_teaches_itemless_release_path() -> None:
    rc, out, err = _help("watch", "deploy", "--help")
    assert rc == 0, err
    assert "resolve the target env" in out
    assert "--project-repo-path" in out
    assert "Verify the resolved target_env" in out
    _assert_itemless_recipe(out)


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
            result={"run_id": "run-20260805-001", "status": "created"},
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
                    rc = cli_main([
                        "deployment-runs", "create",
                        "yoke", "yoke-hosted-stage-no-ci-gate",
                    ])
    assert rc == 0
    assert out.getvalue().strip() == "run-20260805-001"
    assert "watch deploy -- run-20260805-001" in err.getvalue()
    assert "deployment-runs execute" not in err.getvalue()
