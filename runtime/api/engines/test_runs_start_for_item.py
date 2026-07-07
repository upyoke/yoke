"""Regression tests for AC-42/43: ``runs start-for-item`` composer.

Mocks the four primitives the composer wraps so the test surface stays
deterministic and does not require live GitHub or deployment services
. Covers success, missing project / deployment_flow, create-run
failure, add-item failure, and validation failure. Each failure path
verifies the structured handle preserves run_id when relevant and that
``deploy_pipeline`` is never called by the composer.
"""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.engines import runs_start_for_item as composer
from yoke_core.engines.runs_start_for_item import (
    PHASE_ADD_ITEM,
    PHASE_CREATE,
    PHASE_RESOLVE,
    PHASE_VALIDATE,
    StartForItemResult,
    start_for_item,
)


def _patches(
    *,
    item_row=("yoke", "to-prod"),
    target_env="prod",
    run_id="2026-05-19-001",
    add_item_ret="OK",
    validate_ret=(True, "ok"),
    resolve_raises=None,
    create_raises=None,
    add_raises=None,
    validate_raises=None,
):
    """Return a tuple of mock patches covering the composer's helpers."""
    helpers = mock.patch.object(
        composer,
        "_lookup_item_project_and_flow",
        return_value=item_row,
    )
    resolve = mock.patch.object(
        composer, "cmd_resolve_target_env",
        side_effect=resolve_raises if resolve_raises else None,
        return_value=target_env,
    )
    create = mock.patch.object(
        composer, "cmd_create_run",
        side_effect=create_raises if create_raises else None,
        return_value=run_id,
    )
    add = mock.patch.object(
        composer, "cmd_add_item",
        side_effect=add_raises if add_raises else None,
        return_value=add_item_ret,
    )
    validate = mock.patch.object(
        composer, "cmd_validate_composition",
        side_effect=validate_raises if validate_raises else None,
        return_value=validate_ret,
    )
    return helpers, resolve, create, add, validate


def test_success_returns_structured_handle():
    helpers, resolve, create, add, validate = _patches()
    with helpers, resolve, create as create_m, add as add_m, validate:
        result = start_for_item(42)
    assert isinstance(result, StartForItemResult)
    assert result.ok is True
    assert result.run_id == "2026-05-19-001"
    assert result.project == "yoke"
    assert result.flow == "to-prod"
    assert result.target_env == "prod"
    assert result.item_ids == [42]
    assert result.error is None
    create_m.assert_called_once()
    add_m.assert_called_once_with("2026-05-19-001", 42)


def test_explicit_kwargs_override_item_row():
    helpers = mock.patch.object(
        composer, "_lookup_item_project_and_flow",
        return_value=("ignored", "ignored-flow"),
    )
    resolve = mock.patch.object(
        composer, "cmd_resolve_target_env", return_value="staging",
    )
    create = mock.patch.object(
        composer, "cmd_create_run", return_value="R1",
    )
    add = mock.patch.object(composer, "cmd_add_item", return_value="OK")
    validate = mock.patch.object(
        composer, "cmd_validate_composition", return_value=(True, "ok"),
    )
    with helpers, resolve as resolve_m, create as create_m, add, validate:
        result = start_for_item(
            42, project="buzz", flow="to-staging",
        )
    assert result.project == "buzz"
    assert result.flow == "to-staging"
    # The explicit kwargs reach the primitives — not the item row values.
    create_m.assert_called_once()
    args, kwargs = create_m.call_args
    assert args[0] == "buzz"
    assert args[1] == "to-staging"
    resolve_m.assert_called_once_with(
        "buzz", "to-staging", target_env_override=None,
    )


def test_missing_project_short_circuits_before_db_writes():
    helpers, resolve, create, add, validate = _patches(item_row=(None, "x"))
    with helpers, resolve, create as create_m, add as add_m, validate:
        result = start_for_item(42)
    assert result.ok is False
    assert result.error_phase == PHASE_RESOLVE
    assert "no project" in result.error
    assert result.run_id is None
    create_m.assert_not_called()
    add_m.assert_not_called()


def test_missing_deployment_flow_short_circuits():
    helpers, resolve, create, add, validate = _patches(item_row=("yoke", None))
    with helpers, resolve, create as create_m, add as add_m, validate:
        result = start_for_item(42)
    assert result.ok is False
    assert result.error_phase == PHASE_RESOLVE
    assert "deployment_flow" in result.error
    assert result.run_id is None
    create_m.assert_not_called()
    add_m.assert_not_called()


def test_resolve_target_env_raise_is_captured():
    helpers, resolve, create, add, validate = _patches(
        resolve_raises=RuntimeError("env not configured"),
    )
    with helpers, resolve, create as create_m, add as add_m, validate:
        result = start_for_item(42)
    assert result.ok is False
    assert result.error_phase == PHASE_RESOLVE
    assert "env not configured" in result.error
    assert result.run_id is None
    create_m.assert_not_called()
    add_m.assert_not_called()


def test_create_run_failure_returns_no_run_id():
    helpers, resolve, create, add, validate = _patches(
        create_raises=RuntimeError("DB locked"),
    )
    with helpers, resolve, create, add as add_m, validate:
        result = start_for_item(42)
    assert result.ok is False
    assert result.error_phase == PHASE_CREATE
    assert "DB locked" in result.error
    assert result.run_id is None
    add_m.assert_not_called()


def test_add_item_failure_preserves_run_id():
    helpers, resolve, create, add, validate = _patches(
        add_raises=RuntimeError("item not found"),
    )
    with helpers, resolve, create, add, validate as validate_m:
        result = start_for_item(42)
    assert result.ok is False
    assert result.error_phase == PHASE_ADD_ITEM
    # Failure after run creation preserves run_id for inspection/cleanup.
    assert result.run_id == "2026-05-19-001"
    validate_m.assert_not_called()


def test_validate_composition_failure_preserves_run_id_and_blocks_deploy():
    helpers, resolve, create, add, validate = _patches(
        validate_ret=(False, "missing required item"),
    )
    with helpers, resolve, create, add, validate:
        result = start_for_item(42)
    assert result.ok is False
    assert result.error_phase == PHASE_VALIDATE
    assert "missing required item" in result.error
    # AC-43 invariant: validation failure preserves run_id...
    assert result.run_id == "2026-05-19-001"
    # ... and the composer never reached deploy_pipeline. We assert the
    # absence by ensuring deploy_pipeline is not imported by this module
    # (and therefore not callable from the composer's call graph).
    import yoke_core.engines.runs_start_for_item as mod
    assert "deploy_pipeline" not in dir(mod)


def test_validate_composition_raise_captured():
    helpers, resolve, create, add, validate = _patches(
        validate_raises=ValueError("schema mismatch"),
    )
    with helpers, resolve, create, add, validate:
        result = start_for_item(42)
    assert result.ok is False
    assert result.error_phase == PHASE_VALIDATE
    assert "schema mismatch" in result.error
    assert result.run_id == "2026-05-19-001"


def test_to_dict_omits_error_fields_on_success():
    handle = StartForItemResult(
        ok=True, project="p", flow="f", target_env="t",
        run_id="R", validation_message="ok", item_ids=[42],
    )
    out = handle.to_dict()
    assert out["ok"] is True
    assert "error" not in out
    assert "error_phase" not in out
    assert out["validation_message"] == "ok"


def test_to_dict_includes_error_fields_on_failure():
    handle = StartForItemResult(
        ok=False, project="p", flow="f", target_env=None, run_id=None,
        error="missing", error_phase=PHASE_RESOLVE, item_ids=[42],
    )
    out = handle.to_dict()
    assert out["ok"] is False
    assert out["error"] == "missing"
    assert out["error_phase"] == PHASE_RESOLVE
