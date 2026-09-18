"""The done guard reading the shared delivery ladder.

Three behaviours the guard owes an owner at a release wait: a delivery the
flow made closes out however the run was enrolled; an unreadable answer
blocks as unreadable rather than as undelivered; and ``--skip-deploy`` is
refused for a delivery the selected flow demonstrably made, because the
record it writes would be false.
"""

from unittest import mock

from yoke_core.engines import done_transition_deploy_gates as deploy_gates


def _patch_registered_flows(flows):
    return mock.patch.object(
        deploy_gates,
        "_relay_read",
        side_effect=lambda function_id, target, payload=None: (
            {"flow_ids": flows}
            if function_id == "done_transition.registered_flow_ids"
            else {}
        ),
    )


def _patch_target_tier(tier):
    return mock.patch.object(
        deploy_gates, "_read_deployment_flow_target_tier", return_value=tier
    )


def _patch_delivery(verdict):
    return mock.patch.object(
        deploy_gates, "_read_delivery_evidence", return_value=verdict
    )


def _patch_latest_run(status, run_id=""):
    return mock.patch.object(
        deploy_gates, "_get_latest_run_status", return_value=(status, run_id)
    )


def _guard(**kwargs):
    defaults = dict(
        item_id=900,
        deploy_flow="yoke-prod-release",
        skip_deploy=False,
        item_project="yoke",
        old_status="release",
        delivery_stage_id="release",
        public_ref="YOK-900",
    )
    defaults.update(kwargs)
    return deploy_gates._check_deployment_flow_guard(**defaults)


def test_containment_delivery_closes_out_an_unenrolled_member(capsys):
    """No membership row, but the release contains the merge: delivered."""
    with (
        _patch_registered_flows(["yoke-prod-release"]),
        _patch_target_tier("persistent"),
        _patch_delivery({
            "state": "discharged",
            "run_id": "run-4",
            "source": "release_containment",
        }),
        _patch_latest_run(""),
        mock.patch.object(
            deploy_gates, "_check_run_stage_consistency", return_value=False
        ),
        mock.patch.object(deploy_gates, "check_run_qa_gates", return_value=False),
    ):
        result = _guard()
    assert result is None
    assert "proceeding to done" in capsys.readouterr().out


def test_an_unreadable_delivery_answer_blocks_as_unreadable(capsys):
    with (
        _patch_registered_flows(["yoke-prod-release"]),
        _patch_target_tier("persistent"),
        _patch_delivery({
            "state": "undetermined",
            "reason": "repository_provider_read_failed",
            "recovery": "Confirm the project's GitHub binding, then retry.",
        }),
        _patch_latest_run(""),
    ):
        result = _guard()
    out = capsys.readouterr().out
    assert result == (7, "release")
    assert "could not be determined" in out
    assert "unreadable answer, not a negative one" in out
    assert "Do not redeploy to force a verdict" in out


def test_skip_deploy_is_refused_for_a_delivery_the_flow_made(capsys):
    """Recording a selected-flow delivery as out-of-band is a false record."""
    with (
        _patch_registered_flows(["yoke-prod-release"]),
        _patch_target_tier("persistent"),
        _patch_delivery({"state": "discharged", "run_id": "run-4"}),
        _patch_latest_run(""),
    ):
        result = _guard(skip_deploy=True)
    out = capsys.readouterr().out
    assert result == (7, "release")
    assert "already delivered it (run run-4)" in out
    assert "would be a false record" in out
    assert "without --skip-deploy" in out


def test_skip_deploy_still_serves_a_genuinely_out_of_band_delivery(capsys):
    """The flag keeps its real use: delivery the selected flow did not make."""
    with (
        _patch_registered_flows(["yoke-prod-release"]),
        _patch_target_tier("persistent"),
        _patch_delivery({"state": "not_discharged", "reason": "no run"}),
        _patch_latest_run("succeeded", "run-2"),
        mock.patch.object(deploy_gates, "check_run_qa_gates", return_value=False),
    ):
        result = _guard(skip_deploy=True)
    out = capsys.readouterr().out
    assert result is None
    assert "Skipping live deployment pipeline checks per --skip-deploy" in out
