"""Composing a run for an item is gated on the project deploy lock.

The composer stops before ``create-run`` when the calling session does
not hold it, so a second driver cannot start a run against a project
someone else is already deploying.
"""

from __future__ import annotations

from unittest import mock

from yoke_core.engines import runs_start_for_item as composer
from yoke_core.engines.runs_start_for_item import (
    PHASE_DEPLOY_LOCK,
    start_for_item,
)
from runtime.api.engines.runs_start_for_item_test_support import _patches


def test_a_missing_deploy_lock_stops_before_any_run_is_created():
    helpers, resolve, create, add, validate = _patches()
    refusal = (
        "deployment_runs.start_for_item refused: no session holds the deploy "
        "lock DEPLOY:yoke for project 'yoke'."
    )
    with (
        helpers,
        resolve,
        create as create_m,
        add,
        validate,
        mock.patch.object(composer, "deploy_lock_refusal", return_value=refusal),
    ):
        result = start_for_item(42)
    assert result.ok is False
    assert result.error_phase == PHASE_DEPLOY_LOCK
    assert result.error_code == "deploy_lock_required"
    assert "DEPLOY:yoke" in result.error
    create_m.assert_not_called()


def test_the_calling_session_is_who_the_deploy_lock_is_checked_against():
    helpers, resolve, create, add, validate = _patches()
    with (
        helpers,
        resolve,
        create,
        add,
        validate,
        mock.patch.object(
            composer, "deploy_lock_refusal", return_value=None,
        ) as lock,
    ):
        start_for_item(42, session_id="sess-driver")
    assert lock.call_args.args[0] == "yoke"
    assert lock.call_args.kwargs["session_id"] == "sess-driver"
