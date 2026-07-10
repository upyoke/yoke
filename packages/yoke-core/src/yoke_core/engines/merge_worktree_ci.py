"""CI polling helper for merge-worktree PRs.

The local-verification evidence helpers (:func:`classify_test_results`,
:func:`read_item_test_results`) live in
:mod:`yoke_core.domain.item_test_results_classify` — the domain-layer
single source of truth shared with the polish→implemented gate. This
module re-exports the engine-private aliases ``_classify_test_results``
and ``_read_item_test_results`` so existing test monkeypatches keep
working without inverting the architecture-model layer arrow.
"""

from __future__ import annotations

import json
import time
from typing import NamedTuple, Optional

from yoke_core.domain.item_test_results_classify import (
    classify_test_results,
    read_item_test_results,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext
from yoke_core.engines.merge_worktree_ci_rest import (
    CheckRunsState,
    get_check_runs,
)


class CIOutcome(NamedTuple):
    """Tri-state outcome from ``_wait_for_ci``.

    ``outcome`` is one of ``"passed"``, ``"skipped"``, ``"failed"``.
    ``reason`` carries a structured tag when the outcome is ``skipped``
    (today only ``"no_checks_configured"``) so the caller can route the
    skip path without inspecting REST response detail. Passed/failed paths
    leave ``reason=None``.
    """

    outcome: str
    reason: Optional[str] = None


PASSED = CIOutcome("passed")
# Two distinct "skipped" reasons let the substitute gate (and telemetry)
# tell genuinely-no-CI from a declared workflow whose checks never registered.
# Both route to the freshness-bound local
# substitute downstream; the reason rides the MergePullRequestCiSkipped
# event so the distinction is observable.
SKIPPED_NO_CHECKS = CIOutcome("skipped", "no_checks_configured")
SKIPPED_UNREGISTERED = CIOutcome("skipped", "checks_declared_unregistered")
FAILED = CIOutcome("failed")


def _parent():
    from yoke_core.engines import merge_worktree as _mw
    return _mw


_classify_test_results = classify_test_results
_read_item_test_results = read_item_test_results


def _project_declares_ci_workflow(ctx: MergeContext) -> bool:
    """Return True when the merged item's project declares a CI workflow.

    Reads the per-project ``ci_workflow_file`` capability. When a project
    declares a workflow, empty check-runs mean "not registered yet" — the
    poller waits for them rather than concluding no-CI on the first empty
    read. A project with no declaration is genuinely CI-less and
    routes straight to the freshness-bound local substitute.
    """
    project = getattr(ctx, "project", None)
    if not project:
        return False
    try:
        from yoke_core.domain.projects_capabilities_settings import (
            cmd_capability_get_settings,
        )
        from yoke_core.domain.projects_seed_ci_workflow import (
            CI_WORKFLOW_CAPABILITY_TYPE,
        )
        settings = cmd_capability_get_settings(
            project, CI_WORKFLOW_CAPABILITY_TYPE
        )
        if not settings:
            return False
        data = json.loads(settings)
    except Exception:
        return False
    return bool(isinstance(data, dict) and data.get("workflow_file"))


def _classify_states(states: tuple[str, ...]) -> Optional[CIOutcome]:
    """Translate a check-runs state tuple into a terminal CIOutcome.

    Returns None when at least one state is still pending; the poll loop
    handles the sleep / next attempt.
    """
    if not states:
        return SKIPPED_NO_CHECKS
    if any(s in ("PENDING", "QUEUED", "IN_PROGRESS") for s in states):
        return None
    if any(s in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT") for s in states):
        return FAILED
    not_ok = [s for s in states if s not in ("SUCCESS", "NEUTRAL", "SKIPPED")]
    if not_ok:
        return FAILED
    return PASSED


def _wait_for_ci(pr_num: str, ctx: MergeContext) -> CIOutcome:
    """Poll CI status via REST. Returns a :class:`CIOutcome` tri-state.

    Calls ``GET /repos/{o}/{r}/commits/{sha}/check-runs`` for the PR's
    head SHA, translating each check-run's ``status``/``conclusion`` into
    the canonical state vocabulary the legacy helper produced (SUCCESS,
    FAILURE, PENDING, etc.). When the token cannot read check-runs at all
    or no check-runs are configured, the helper fails authorization errors
    and returns :data:`SKIPPED_NO_CHECKS` only for a readable empty result.
    Terminal failure classes emit ``MergePullRequestCiFailed``.
    """
    from yoke_core.domain import runtime_settings

    mw = _parent()
    _print = mw._print
    _fail_merge_rest = mw._fail_merge_rest

    if not pr_num:
        return PASSED

    _print("")
    _print("Waiting for CI checks...")

    def _query_states() -> tuple[Optional[CheckRunsState], Optional[str]]:
        return get_check_runs(ctx, pr_num)

    initial_state, initial_err = _query_states()
    if initial_err is not None:
        _fail_merge_rest(
            "pr-checks-initial",
            ctx=ctx,
            event_name="MergePullRequestCiFailed",
            error_detail=initial_err,
            extra_detail=(
                f"REST check-runs read for PR {pr_num} failed before the "
                "polling loop started. Treating as CI failure; worktree "
                "preserved."
            ),
        )
        return FAILED
    assert initial_state is not None
    poll_interval = runtime_settings.get_seconds("ci_poll_interval", 30)

    # Empty check-runs. When the project declares a CI workflow the
    # runs may not be registered on the head SHA yet — wait a bounded window
    # for them to appear before concluding no-CI. A project with no declared
    # workflow is genuinely CI-less and routes to the local substitute.
    if not initial_state.states:
        if not _project_declares_ci_workflow(ctx):
            _print("(No CI checks configured — skipping)")
            return SKIPPED_NO_CHECKS
        reg_timeout = runtime_settings.get_seconds(
            "ci_registration_timeout", 120
        )
        _print(
            f"CI workflow declared; waiting up to {reg_timeout}s for checks "
            "to register..."
        )
        reg_elapsed = 0
        while reg_elapsed < reg_timeout:
            time.sleep(poll_interval)
            reg_elapsed += poll_interval
            reg_state, reg_err = _query_states()
            if reg_err is not None:
                _fail_merge_rest(
                    "pr-checks-registration",
                    ctx=ctx,
                    event_name="MergePullRequestCiFailed",
                    error_detail=reg_err,
                    extra_detail=(
                        f"REST check-runs read for PR {pr_num} failed while "
                        "waiting for checks to register. Treating as CI "
                        "failure."
                    ),
                )
                return FAILED
            assert reg_state is not None
            if reg_state.states:
                initial_state = reg_state
                break
        else:
            _print(
                "(CI workflow declared but no checks registered in time "
                "— skipping)"
            )
            return SKIPPED_UNREGISTERED

    timeout = runtime_settings.get_seconds("ci_timeout", 1800)
    elapsed = 0
    latest = initial_state

    while elapsed < timeout:
        outcome = _classify_states(latest.states)
        if outcome is not None:
            if outcome.outcome == "passed":
                _print("CI passed.")
            elif outcome.outcome == "failed":
                _print("CI failed.", err=True)
            return outcome

        time.sleep(poll_interval)
        elapsed += poll_interval
        next_state, next_err = _query_states()
        if next_err is not None:
            _fail_merge_rest(
                "pr-checks-poll",
                ctx=ctx,
                event_name="MergePullRequestCiFailed",
                error_detail=next_err,
                extra_detail=(
                    f"REST check-runs read for PR {pr_num} failed during "
                    f"polling at elapsed={elapsed}s.  Treating as CI failure."
                ),
            )
            return FAILED
        assert next_state is not None
        if not next_state.states:
            _print("(No CI checks configured — skipping)")
            return SKIPPED_NO_CHECKS
        latest = next_state

    _print(f"CI timeout after {timeout}s", err=True)
    return FAILED
