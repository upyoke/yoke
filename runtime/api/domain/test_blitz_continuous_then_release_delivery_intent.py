"""A still-implementing Blitz keeps progress delivery; final closeout does not.

Blitz's delivery policy is the hybrid continuous_slice_then_release_stage:
continuous per-slice progress deploys stay available exactly as they were
under the old continuous_slice_actions policy, while only its release-stage
predecessor (and the terminal stage) close the window explicit progress
delivery opens.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.deployment_run_composition_freeze import (
    validate_delivery_intent_for_item,
)


def _blitz(conn: Any, item_id: int, status: str) -> None:
    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id,
        workflow_id="blitz",
        status=status,
    )


def test_progress_intent_is_valid_while_still_implementing(test_db: Any) -> None:
    _blitz(test_db, 9501, "implementing")

    assert (
        validate_delivery_intent_for_item(test_db, 9501, "progress") == "progress"
    )


def test_progress_intent_is_valid_through_review_before_release(
    test_db: Any,
) -> None:
    _blitz(test_db, 9502, "reviewing-implementation")

    assert (
        validate_delivery_intent_for_item(test_db, 9502, "progress") == "progress"
    )


def test_progress_intent_is_still_valid_at_the_release_stage(test_db: Any) -> None:
    """The release-stage wait narrows the DEFAULT intent to final; it does not
    forbid an explicit progress request — only the terminal stage does."""
    _blitz(test_db, 9503, "release")

    assert (
        validate_delivery_intent_for_item(test_db, 9503, "progress") == "progress"
    )


def test_progress_intent_is_rejected_once_done(test_db: Any) -> None:
    """A terminal item refuses upstream, before the progress-specific check."""
    _blitz(test_db, 9504, "done")

    with pytest.raises(ValueError, match="terminal"):
        validate_delivery_intent_for_item(test_db, 9504, "progress")


def test_final_intent_is_always_valid_regardless_of_status(test_db: Any) -> None:
    _blitz(test_db, 9505, "implementing")

    assert validate_delivery_intent_for_item(test_db, 9505, "final") == "final"


def test_no_explicit_intent_passes_through_unvalidated(test_db: Any) -> None:
    _blitz(test_db, 9506, "release")

    assert validate_delivery_intent_for_item(test_db, 9506, None) is None
