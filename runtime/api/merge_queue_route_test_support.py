# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from runtime.api.merge_queue_landing_test_helpers import (
    ARMED,
    HELD_BY_THIS_SESSION,
    MERGED,
    UNARMED,
    dispatch_for,
    land,
    landing_record,
    wire_happy_path,
)

from yoke_contracts.designed_wait import DESIGNED_WAIT_PREFIX

from yoke_core.domain import merge_queue_landing_pull_request as landing_pr_mod

from yoke_core.domain import merge_queue_failed_train as failed_train_mod

from yoke_core.domain import merge_queue_landing_timeout as timeout_mod

from yoke_core.domain import merge_queue_route as route_mod

from yoke_core.domain import session_liveness_pump as liveness_mod

from yoke_core.domain.merge_queue_landing_record_state import PENDING

from yoke_core.domain.session_liveness_pump import SessionLivenessPump

from yoke_core.engines.merge_worktree_pr_queue import QueueMember

from yoke_core.engines.merge_worktree_pr_train_run import TrainRun

from runtime.api.merge_queue_landing_test_helpers import LANE_SHA


def stalled_clock(step=40.0):
    """A monotonic that walks past any deadline the caller sets."""
    now = {"t": 0.0}

    def monotonic():
        now["t"] += step
        return now["t"]

    return monotonic
