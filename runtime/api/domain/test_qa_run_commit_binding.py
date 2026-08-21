"""Commit-bound hand-run recording refuses prose and stamps a clean lane."""

from __future__ import annotations

import json

from yoke_core.domain.qa_merging_identity import recorded_head_sha
from yoke_core.domain.qa_run_commit_binding import (
    DIRTY_TREE,
    NO_LANE,
    REQUIRED_SHAPE,
    bind_recorded_raw_result,
    wrap_evidence,
)

SHA = "a" * 40
OTHER = "b" * 40


def _bind(**overrides):
    kwargs = {
        "verdict": "pass",
        "raw_result": "Final tree passed",
        "performed_by": "agent",
        "blocking_mode": "blocking",
        "waived_at": None,
        "resolve_lane": lambda: ("", "", "no_lane"),
    }
    kwargs.update(overrides)
    return bind_recorded_raw_result(**kwargs)


def test_hand_run_without_sha_is_refused_and_names_the_shape():
    bound, error = _bind()
    assert bound == "Final tree passed"
    assert error == NO_LANE
    assert "verification_tree" in error
    assert "head_sha" in error
    assert REQUIRED_SHAPE in error


def test_dirty_lane_refuses_with_named_reason():
    bound, error = _bind(resolve_lane=lambda: ("/lane", "", "dirty_tree"))
    assert bound == "Final tree passed"
    assert error == DIRTY_TREE
    assert error.startswith("dirty_tree:")


def test_clean_lane_stamps_head_and_keeps_prose_as_evidence():
    bound, error = _bind(resolve_lane=lambda: ("/lane", SHA, ""))
    assert error == ""
    assert recorded_head_sha(bound) == SHA
    assert json.loads(bound)["evidence"] == "Final tree passed"
    assert json.loads(bound)["verification_tree"]["root"] == "/lane"


def test_explicit_head_sha_skips_dirty_lane():
    bound, error = _bind(
        head_sha=OTHER, resolve_lane=lambda: ("/lane", "", "dirty_tree"),
    )
    assert error == ""
    assert recorded_head_sha(bound) == OTHER


def test_existing_json_sha_is_kept():
    raw = wrap_evidence("already bound", SHA)
    bound, error = _bind(
        raw_result=raw, resolve_lane=lambda: ("/lane", "", "dirty_tree"),
    )
    assert error == ""
    assert recorded_head_sha(bound) == SHA


def test_non_blocking_and_fail_are_left_alone():
    prose = "not identity"
    bound, error = _bind(blocking_mode="non_blocking", raw_result=prose)
    assert (bound, error) == (prose, "")
    bound, error = _bind(verdict="fail", raw_result=prose)
    assert (bound, error) == (prose, "")


def test_runner_empty_pass_is_not_forced_without_a_lane():
    bound, error = _bind(
        performed_by="pytest", raw_result=None, resolve_lane=lambda: ("", "", "no_lane"),
    )
    assert (bound, error) == (None, "")
