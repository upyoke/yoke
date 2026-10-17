"""Regression tests for the ``runs start-for-item`` composer.

Mocks the primitives the composer wraps so the test surface stays
deterministic and does not require live GitHub or deployment services.
Covers success, missing project / deployment_flow, create-run failure,
takeover refusal, and validation failure. A refused creation wrote nothing,
so no failure carries a run_id, and ``deploy_pipeline`` is never called by
the composer.
"""

from __future__ import annotations

from unittest import mock

from runtime.api.engines.runs_start_for_item_test_support import _patches
from yoke_core.domain.deployment_run_create_write import CompositionRefused, CreatedRun
from yoke_core.domain.deployment_run_takeover_authority import (
    RESERVED_FOR_STEERING_CODE,
)
from yoke_core.domain.deployment_run_target_takeover import TakeoverRefused
from yoke_core.engines import runs_start_for_item as composer
from yoke_core.engines.runs_start_for_item import (
    PHASE_CREATE,
    PHASE_RESOLVE,
    PHASE_VALIDATE_LINEAGE,
    PHASE_VALIDATE,
    StartForItemResult,
    start_for_item,
)
from yoke_core.domain.project_identity_item_ref import item_ref_for_id


def test_success_returns_structured_handle():
    helpers, resolve, tested, create = _patches()
    with helpers, resolve, tested, create as create_m:
        result = start_for_item(42)
    assert isinstance(result, StartForItemResult)
    assert result.ok is True
    assert result.run_id == "2026-05-19-001"
    assert result.project == "yoke"
    assert result.flow == "to-prod"
    assert result.target_tier == "persistent"
    assert result.target_environment_id == 101
    assert result.target_environment_name == "prod"
    assert result.item_ids == [42]
    assert result.error is None
    assert result.validation_message == "ok"
    create_m.assert_called_once()
    assert create_m.call_args.kwargs["enroll_item_id"] == 42


def test_explicit_kwargs_override_item_row():
    helpers = mock.patch.object(
        composer,
        "_lookup_item_project_and_flow",
        return_value=("ignored", "ignored-flow"),
    )
    resolve = mock.patch.object(
        composer,
        "cmd_resolve_target",
        return_value=("persistent", 102, "preview"),
    )
    create = mock.patch.object(
        composer,
        "create_run",
        return_value=CreatedRun("R1", False, None, "ok"),
    )
    tested = mock.patch.object(composer, "require_tested_lineage")
    with helpers, resolve as resolve_m, tested, create as create_m:
        result = start_for_item(
            42,
            project="externalwebapp",
            flow="to-staging",
        )
    assert result.project == "externalwebapp"
    assert result.flow == "to-staging"
    # The explicit kwargs reach the primitives — not the item row values.
    create_m.assert_called_once()
    args, kwargs = create_m.call_args
    assert args[0] == "externalwebapp"
    assert args[1] == "to-staging"
    resolve_m.assert_called_once_with(
        "externalwebapp",
        "to-staging",
        environment_override=None,
    )


def test_item_without_flow_uses_its_workflow_specific_project_default():
    conn = mock.MagicMock()
    conn.execute.return_value.fetchone.return_value = ("yoke", None, "dash")
    with (
        mock.patch(
            "yoke_core.domain.db_helpers.connect",
            return_value=conn,
        ),
        mock.patch(
            "yoke_core.domain.workflow_project_defaults.get_delivery_default",
            return_value="dash-production",
        ) as resolve_default,
    ):
        project, flow = composer._lookup_item_project_and_flow(42)

    assert (project, flow) == ("yoke", "dash-production")
    resolve_default.assert_called_once_with(
        conn,
        project="yoke",
        workflow_id="dash",
    )
    conn.close.assert_called_once()


def test_missing_project_short_circuits_before_db_writes():
    helpers, resolve, tested, create = _patches(item_row=(None, "x"))
    with helpers, resolve, tested, create as create_m:
        result = start_for_item(42)
    assert result.ok is False
    assert result.error_phase == PHASE_RESOLVE
    assert "no project" in result.error
    assert result.run_id is None
    create_m.assert_not_called()


def test_missing_deployment_flow_short_circuits():
    helpers, resolve, tested, create = _patches(item_row=("yoke", None))
    with helpers, resolve, tested, create as create_m:
        result = start_for_item(42)
    assert result.ok is False
    assert result.error_phase == PHASE_RESOLVE
    assert "deployment_flow" in result.error
    assert result.run_id is None
    create_m.assert_not_called()


def test_missing_flow_refusal_carries_the_flow_selection_recovery():
    helpers, resolve, tested, create = _patches(item_row=("yoke", None))
    # The refusal names the item the way a reader sees it, so the describer
    # is handed the rendered reference rather than the internal id.
    recovery = "PREFIX-N has no deployment_flow; pass --flow with one of: to-prod"
    describe = mock.patch.object(
        composer,
        "_describe_missing_flow",
        return_value=recovery,
    )
    with helpers, resolve, tested, create, describe as describe_m:
        result = start_for_item(42)
    assert result.ok is False
    assert result.error == recovery
    describe_m.assert_called_once_with(item_ref_for_id(42), "yoke")


def test_resolve_target_raise_is_captured():
    helpers, resolve, tested, create = _patches(
        resolve_raises=RuntimeError("env not configured"),
    )
    with helpers, resolve, tested, create as create_m:
        result = start_for_item(42)
    assert result.ok is False
    assert result.error_phase == PHASE_RESOLVE
    assert "env not configured" in result.error
    assert result.run_id is None
    create_m.assert_not_called()


def test_create_run_failure_returns_no_run_id():
    helpers, resolve, tested, create = _patches(
        create_raises=RuntimeError("DB locked"),
    )
    with helpers, resolve, tested, create:
        result = start_for_item(42)
    assert result.ok is False
    assert result.error_phase == PHASE_CREATE
    assert "DB locked" in result.error
    assert result.run_id is None


def test_stage_run_without_lineage_binds_exact_remote_head_before_create():
    remote_sha = "a" * 40
    helpers, resolve, tested, create = _patches(
        target=("persistent", 103, "stage"),
    )
    with (
        helpers,
        resolve,
        tested,
        create as create_m,
        mock.patch.object(
            composer,
            "_resolve_remote_release_head",
            return_value=(remote_sha, ""),
        ) as resolve_head,
    ):
        result = start_for_item(42)

    assert result.ok is True
    resolve_head.assert_called_once_with(
        "yoke",
        "persistent",
        "stage",
        "",
    )
    assert create_m.call_args.kwargs["release_lineage"] == remote_sha


def test_explicit_sha_lineage_is_rejected_before_run_insert_when_not_remote_head():
    candidate = "b" * 40
    helpers, resolve, tested, create = _patches(
        target=("persistent", 103, "stage"),
    )
    lineage_check = mock.patch.object(
        composer,
        "_validate_commit_release_lineage",
        return_value="release_lineage does not equal the remote gate-branch commit",
    )
    with helpers, resolve, tested, create as create_m, lineage_check:
        result = start_for_item(42, release_lineage=candidate)

    assert result.ok is False
    assert result.error_phase == PHASE_VALIDATE_LINEAGE
    assert "remote gate-branch commit" in result.error
    create_m.assert_not_called()


def test_takeover_refusal_names_its_code_and_creates_nothing():
    helpers, resolve, tested, create = _patches(
        create_raises=TakeoverRefused(RESERVED_FOR_STEERING_CODE, "seat holds it"),
    )
    with helpers, resolve, tested, create:
        result = start_for_item(42)
    assert result.ok is False
    assert result.error_phase == PHASE_CREATE
    assert result.error_code == RESERVED_FOR_STEERING_CODE
    assert result.run_id is None


def test_validate_composition_failure_creates_nothing_and_blocks_deploy():
    helpers, resolve, tested, create = _patches(
        create_raises=CompositionRefused("missing required item"),
    )
    with helpers, resolve, tested, create:
        result = start_for_item(42)
    assert result.ok is False
    assert result.error_phase == PHASE_VALIDATE
    assert "missing required item" in result.error
    assert result.validation_message == "missing required item"
    # The refused composition rolled the run back, so there is none to name...
    assert result.run_id is None
    # ... and the composer never reached deploy_pipeline. We assert the
    # absence by ensuring deploy_pipeline is not imported by this module
    # (and therefore not callable from the composer's call graph).
    import yoke_core.engines.runs_start_for_item as mod

    assert "deploy_pipeline" not in dir(mod)


def test_to_dict_omits_error_fields_on_success():
    handle = StartForItemResult(
        ok=True,
        project="p",
        flow="f",
        target_tier="persistent",
        target_environment_id=101,
        target_environment_name="prod",
        run_id="R",
        validation_message="ok",
        item_ids=[42],
    )
    out = handle.to_dict()
    assert out["ok"] is True
    assert "error" not in out
    assert "error_phase" not in out
    assert out["validation_message"] == "ok"


def test_to_dict_includes_error_fields_on_failure():
    handle = StartForItemResult(
        ok=False,
        project="p",
        flow="f",
        run_id=None,
        error="missing",
        error_phase=PHASE_RESOLVE,
        item_ids=[42],
    )
    out = handle.to_dict()
    assert out["ok"] is False
    assert out["error"] == "missing"
    assert out["error_phase"] == PHASE_RESOLVE
