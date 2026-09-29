"""The run-status vocabulary matches the column it describes, and fails closed.

The point of naming these statuses once is that a reader deciding whether a
run's resources may be released cannot drift from what the column accepts.
So this pins both halves: the vocabulary is exactly the live CHECK constraint's
set, and an unknown value is neither open nor terminal.
"""

from __future__ import annotations

import pytest

from yoke_contracts.deployment_run_lifecycle import (
    DEPLOYMENT_RUN_STATUSES,
    OPEN_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    run_is_open,
    run_is_terminal,
)


def test_open_and_terminal_partition_the_vocabulary():
    assert set(OPEN_RUN_STATUSES) | set(TERMINAL_RUN_STATUSES) == set(
        DEPLOYMENT_RUN_STATUSES
    )
    assert not set(OPEN_RUN_STATUSES) & set(TERMINAL_RUN_STATUSES)


def test_the_vocabulary_is_what_the_column_accepts():
    """Drift here is what makes a sweep reclaim something still in use."""
    assert set(DEPLOYMENT_RUN_STATUSES) == {
        "created",
        "executing",
        "succeeded",
        "failed",
        "cancelled",
    }


@pytest.mark.parametrize("status", TERMINAL_RUN_STATUSES)
def test_terminal_statuses_read_as_final(status: str):
    assert run_is_terminal(status)
    assert not run_is_open(status)


@pytest.mark.parametrize("status", OPEN_RUN_STATUSES)
def test_open_statuses_read_as_unfinished(status: str):
    assert run_is_open(status)
    assert not run_is_terminal(status)


@pytest.mark.parametrize("status", ["", "  ", "quiesced", "SUCCEEDED", None])
def test_an_unknown_status_is_neither(status):
    """Allowlists in both directions: "not open" never means "finished"."""
    assert not run_is_terminal(status)
    assert not run_is_open(status)


def test_surrounding_whitespace_does_not_hide_a_status():
    assert run_is_terminal(" succeeded ")
    assert run_is_open(" executing ")
