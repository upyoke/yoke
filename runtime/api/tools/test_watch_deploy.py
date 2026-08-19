"""The deploy watcher's line classification, guard, and registration.

A deploy is the longest command an operator runs, so the filter has to
carry both halves of the signal: enough progress that silence is not
indistinguishable from a hang, and every terminal shape that ends a run.
"""

from __future__ import annotations

import pytest

from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_contracts.watch_cli_forms import WATCH_CLI_TOKENS, cli_form
from yoke_core.tools import watch_deploy
from yoke_core.tools._watch_throttle import LineClass
from yoke_core.tools.watch_entrypoints import WRAPPER_MAINS


def _line_class(line: str) -> LineClass:
    return watch_deploy.classify_deploy_line(line).cls


@pytest.mark.parametrize(
    "line",
    [
        "Error: stage 'hosted-release' failed (exit code: 1)",
        "Step runner diagnostic: failed:failure",
        "ERROR: something broke",
        "fatal: could not read from remote",
    ],
)
def test_terminal_failure_shapes_are_urgent(line):
    """Every shape that ends a deploy has to reach the operator."""
    assert _line_class(line) == LineClass.URGENT


def test_an_unavailable_relay_is_urgent_although_the_pipeline_retries():
    """The failure that spends a release's wall clock without ending it.

    The pipeline keeps retrying inside its stage budget, so this is not a
    terminal line -- and treating it as routine progress is exactly how a
    run burns half an hour looking identical to a healthy one.
    """
    line = (
        "  GitHub Actions status relay is temporarily unavailable; retrying "
        "within the 7200s stage budget (consecutive failure 26)"
    )
    assert _line_class(line) == LineClass.URGENT


@pytest.mark.parametrize(
    "line",
    [
        "--- Stage: hosted-release (step_runner: github-actions-workflow) ---",
        "Pipeline complete for run run-20260805-005",
        "Deployment authority: release_control_plane=prod target_env=stage",
        "  Workflow run ID: 30970494088",
        "  Stage 'hosted-release' completed successfully",
        "Run run-20260805-005 has no member items (environment-level deploy)",
    ],
)
def test_stage_boundaries_and_identifiers_are_summary(line):
    assert _line_class(line) == LineClass.SUMMARY


def test_a_status_poll_is_progress_carrying_its_elapsed_seconds():
    """Elapsed is the only monotonic quantity a deploy emits.

    Handing it to the throttle lets repetitive polls coalesce the way a
    percentage does for a test run.
    """
    classification = watch_deploy.classify_deploy_line(
        "  Workflow status: in_progress (elapsed: 407s, next poll: 30s)"
    )
    assert classification.cls == LineClass.PROGRESS
    assert classification.progress_value == 407.0


def test_unremarkable_output_is_noise():
    assert _line_class("exec-auto: stage complete (no-op)") == LineClass.NOISE


def test_non_qa_stage_diagnostics_are_not_summary_output():
    line = "Stage 'merged' is not a QA stage; no verdict to record"
    assert _line_class(line) == LineClass.NOISE
    assert not watch_deploy.DEPLOY_PROGRESS_PATTERN.search(line)


def test_the_union_pattern_matches_every_classified_shape():
    """The public pattern and the classifier cannot disagree."""
    for line in (
        "Error: stage failed",
        "--- Stage: merged (step_runner: auto) ---",
        "  Workflow status: in_progress (elapsed: 12s, next poll: 30s)",
        "  Workflow run ID: 1",
    ):
        assert watch_deploy.DEPLOY_PROGRESS_PATTERN.search(line), line


def test_a_non_admin_connection_is_refused_with_the_owner_only_recipe(
    monkeypatch,
):
    """The wrapper repeats the execute adapter's guard.

    The run row is readable only through the control plane's db-admin
    connection; a wrapper that skipped this would become the unguarded way
    to reach the same engine.
    """
    monkeypatch.setenv(ENV_OVERRIDE, "prod")
    refusal = watch_deploy.owner_only_connection_error()
    assert refusal is not None
    assert "owner-only" in refusal
    assert "CONTROL-PLANE" in refusal


def test_an_admin_connection_passes_the_guard(monkeypatch):
    monkeypatch.setenv(ENV_OVERRIDE, "prod-db-admin")
    assert watch_deploy.owner_only_connection_error() is None


def test_a_missing_env_is_refused_rather_than_defaulted(monkeypatch):
    monkeypatch.delenv(ENV_OVERRIDE, raising=False)
    assert watch_deploy.owner_only_connection_error() is not None


def test_the_wrapper_drives_the_same_engine_the_execute_adapter_drives():
    """Drift here would mean the watcher runs something else entirely."""
    from yoke_cli.commands import deployment_execute

    assert ("deployment-runs", "execute") in (
        deployment_execute.TOOL_SHAPED_SUBCOMMANDS
    )
    assert watch_deploy.ENGINE_MODULE == "yoke_core.domain.deploy_pipeline"


def test_the_wrapper_is_reachable_from_both_registries():
    """A wrapper nothing routes to is a wrapper that gets bypassed."""
    assert watch_deploy.WRAPPER_MODULE in WRAPPER_MAINS
    assert WRAPPER_MAINS[watch_deploy.WRAPPER_MODULE] is watch_deploy.main
    assert WATCH_CLI_TOKENS[watch_deploy.WRAPPER_MODULE] == ("watch", "deploy")
    assert cli_form(watch_deploy.WRAPPER_MODULE) == "yoke watch deploy"


def test_a_run_id_is_required(capsys):
    monkeypatch_env = pytest.MonkeyPatch()
    monkeypatch_env.setenv(ENV_OVERRIDE, "prod-db-admin")
    try:
        assert watch_deploy.main([]) == 2
        assert "missing run id" in capsys.readouterr().err
    finally:
        monkeypatch_env.undo()
