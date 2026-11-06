"""Failure summaries ignore step environments and prefer explicit diagnostics."""

import pytest

from yoke_core.domain.deployment_failure_trace import (
    FailedJob,
    RunSnapshot,
    github_run_ref,
    terminal_error,
    walk_failure_chain,
)


@pytest.mark.parametrize("prefix", ["", "2026-11-06T15:45:00.1234567Z "])
def test_environment_values_cannot_become_errors(prefix):
    lines = [
        "##[group]Run release",
        "env:",
        "  YOKE_STAGE_DISTRIBUTION_ORIGIN_ID: yoke-stage-distribution-static",
        "  ERROR: misleading environment diagnostic",
        "  TRACE: Traceback (most recent call last):",
        "##[endgroup]",
        "##[error]promotion_owner_ended: start a new deployment run",
        "##[error]Process completed with exit code 1.",
    ]
    assert terminal_error("\n".join(prefix + line for line in lines)) == (
        "promotion_owner_ended: start a new deployment run"
    )


def test_environment_without_error_does_not_supply_a_diagnostic():
    assert terminal_error("env:\n  ValueError: misleading\n##[endgroup]") is None


def test_exception_shaped_plain_text_requires_a_traceback():
    assert terminal_error("Configuration: a very long setting value") is None
    assert terminal_error(
        "ValueError: outside a traceback\nHTTP 503 unavailable"
    ) == "HTTP 503 unavailable"
    assert (
        terminal_error(
            "Traceback (most recent call last):\nValueError: invalid release"
        )
        == "ValueError: invalid release"
    )


def test_annotation_outranks_unannotated_diagnostic_across_jobs():
    ref = github_run_ref("owner/repo", "100")
    snapshot = RunSnapshot(
        ref,
        (
            FailedJob("1", "registry", "unauthorized: authentication required"),
            FailedJob("2", "validate", "##[error]release owner ended"),
        ),
    )
    result = walk_failure_chain(
        ref,
        inspect_run=lambda _: snapshot,
        resolve_job=lambda *_: ref,
    )
    assert result["terminal_job"] == "validate"
    assert result["terminal_error"] == "release owner ended"


def test_environment_block_ends_before_unindented_output():
    assert (
        terminal_error("env:\n  ERROR: misleading\n##[error]real cause") == "real cause"
    )


def test_ended_promotion_job_log_reports_owner_failure():
    # Redacted validate annotated release log from the failed promotion.
    log = (
        '2026-11-06T15:45:31.2130455Z ##[group]Run python3 -m ops.promotion_owner --release-mode "$RELEASE_MODE" --target-environment "$TARGET_ENVIRONMENT" --product-sha "$PRODUCT_SHA"\n'
        '2026-11-06T15:45:31.2131413Z \x1b[36;1mpython3 -m ops.promotion_owner --release-mode "$RELEASE_MODE" --target-environment "$TARGET_ENVIRONMENT" --product-sha "$PRODUCT_SHA"\x1b[0m\n'
        "2026-11-06T15:45:31.2145412Z shell: /usr/bin/bash -e {0}\n"
        "2026-11-06T15:45:31.2145689Z env:\n"
        "2026-11-06T15:45:30.1375171Z   YOKE_STAGE_DISTRIBUTION_ORIGIN_ID: yoke-stage-distribution-static\n"
        "2026-11-06T15:45:31.2148719Z   GH_TOKEN: ***\n"
        "2026-11-06T15:45:31.2148939Z   RELEASE_MODE: normal\n"
        "2026-11-06T15:45:31.2149171Z   TARGET_ENVIRONMENT: prod\n"
        "2026-11-06T15:45:31.2149456Z   PRODUCT_SHA: a05896cbf6d878453251a3d0cc3a2b906d212849\n"
        "2026-11-06T15:45:31.2149901Z ##[endgroup]\n"
        "2026-11-06T15:45:31.6369492Z ##[error]promotion_owner_ended: no in-progress platform-release-bridge.yml run in upyoke/yoke owns normal prod yoke@a05896cbf6d878453251a3d0cc3a2b906d212849; its Yoke deployment run ended, so this promotion stops before deploying. Start a new Yoke deployment run to release\n"
        "2026-11-06T15:45:31.6433341Z ##[error]Process completed with exit code 1.\n"
    )
    diagnostic = terminal_error(log)
    assert diagnostic.startswith("promotion_owner_ended:")
    assert "Start a new Yoke deployment run to release" in diagnostic
