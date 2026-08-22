"""Event internals accept resolved ids, never project-blind prefix tails."""

from __future__ import annotations

import pytest

from yoke_core.domain.events_crud import (
    decompose_work_unit,
    normalize_event_item_id,
)


@pytest.mark.parametrize(
    "ref",
    [
        "YOK-1907",
        "PLAT-123",
        "EXT-45",
        "A-7",
        "yok-1907",
        "plat-123",
        "PLAT-007",
    ],
)
def test_public_refs_are_not_coerced_to_internal_ids(ref) -> None:
    assert normalize_event_item_id(ref) is None


@pytest.mark.parametrize("value, expected", [("42", "42"), ("0042", "42")])
def test_resolved_internal_ids_normalize(value, expected) -> None:
    assert normalize_event_item_id(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "epic-1318-task-3",
        "run-20260417-002",
        "STRATEGIZE",
        "DOCTOR",
        "",
        None,
    ],
)
def test_composites_and_sentinels_are_still_rejected(value) -> None:
    """Composite and sentinel work units never enter the numeric index."""
    assert normalize_event_item_id(value) is None


def test_decompose_keeps_epic_task_and_sentinel_routing() -> None:
    assert decompose_work_unit("PLAT-123") == (None, None, "PLAT-123")
    assert decompose_work_unit("epic-1318-task-3") == ("1318", 3, None)
    assert decompose_work_unit("run-20260417-002") == (
        None,
        None,
        "run-20260417-002",
    )
    assert decompose_work_unit("STRATEGIZE") == (None, None, "STRATEGIZE")
