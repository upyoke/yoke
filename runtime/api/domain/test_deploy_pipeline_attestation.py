"""Deploy pipeline output names an attestation-changing carried-work warning."""

from __future__ import annotations

from unittest import mock

from yoke_core.domain import (
    deploy_pipeline,
    deploy_pipeline_gates,
    deploy_pipeline_run_context,
    deploy_pipeline_run_updates,
)

SHA = "b" * 40
RECOVERY = "Refresh origin, then re-drive the run."
BASIS = {"schema": 1, "primary_project": "yoke", "projects": []}


def _drive(capsys, monkeypatch, carried_work):
    monkeypatch.setenv("YOKE_ENV", "prod")
    run_id = "run-attest-001"
    context = {
        "run": {
            "id": run_id,
            "project": "yoke",
            "flow": "flow-env",
            "target_tier": "persistent",
            "target_environment": "stage",
            "release_lineage": "d" * 40,
            "status": "created",
            "current_stage": "",
            "carried_work": carried_work,
        },
        "members": [],
        "stages": [
            {"name": "merged", "step_runner": "auto"},
            {"name": "complete", "step_runner": "auto"},
        ],
        "candidate_containment_basis": BASIS,
    }

    def fake_dispatch(stage, **kwargs):
        return 0, ""

    with (
        mock.patch.object(
            deploy_pipeline,
            "resolve_flow_gate_branch",
            return_value="stage",
        ),
        mock.patch.object(
            deploy_pipeline,
            "validate_itemless_product_source",
            return_value=mock.Mock(repo_path="/pinned/product", image_tag="abc"),
        ),
        mock.patch.object(
            deploy_pipeline.control_plane,
            "execution_context",
            return_value=context,
        ),
        mock.patch.object(deploy_pipeline_run_updates, "start_run") as start_run,
        mock.patch.object(deploy_pipeline_run_updates, "update_run_field"),
        mock.patch.object(
            deploy_pipeline.control_plane,
            "project_field",
            return_value="",
        ),
        mock.patch.object(deploy_pipeline.control_plane, "seed_qa", return_value=0),
        mock.patch.object(
            deploy_pipeline,
            "resolve_project_checkout_path",
            return_value="/repo",
        ),
        mock.patch.object(deploy_pipeline_run_context, "_emit_run_event"),
        mock.patch.object(deploy_pipeline_gates, "_verify_branch_merged"),
        mock.patch.object(
            deploy_pipeline.stage_receipt,
            "dispatch_step_runner_with_receipt",
            side_effect=fake_dispatch,
        ),
        mock.patch.object(deploy_pipeline, "_emit_run_event"),
        mock.patch.object(deploy_pipeline.control_plane, "record_qa_stage"),
        mock.patch.object(
            deploy_pipeline.control_plane,
            "unresolved_qa",
            return_value=[],
        ),
    ):
        rc = deploy_pipeline.run_pipeline(
            run_id,
            product_repo_path="/pinned/product",
            image_tag="abc",
            sd="/tmp/sd",
        )
    return rc, capsys.readouterr().out, start_run.call_args


def test_pipeline_prints_attestation_warning_cost_and_recovery(
    capsys,
    monkeypatch,
) -> None:
    carried = {
        "derivation": {"contents_known": True},
        "items": [{"commit_shas": [SHA]}],
        "warnings": [
            {"reason": "checkout_not_refreshed", "recovery": RECOVERY},
        ],
    }
    rc, out, start_call = _drive(capsys, monkeypatch, carried)
    assert rc == deploy_pipeline.EXIT_SUCCESS
    assert start_call == mock.call("run-attest-001", BASIS, "/repo")
    assert "carried-work attestation: checkout_not_refreshed" in out
    assert SHA in out
    assert "ancestry residual" in out
    assert f"Recovery: {RECOVERY}" in out


def test_pipeline_prints_nothing_extra_without_attestation_warnings(
    capsys,
    monkeypatch,
) -> None:
    rc, out, _start_call = _drive(
        capsys,
        monkeypatch,
        {"derivation": {"contents_known": True}, "items": [], "warnings": []},
    )
    assert rc == deploy_pipeline.EXIT_SUCCESS
    assert "carried-work attestation" not in out
