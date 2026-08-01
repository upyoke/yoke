"""Event item-ref normalization accepts any project's item prefix.

Each project sets its own `public_item_prefix`, so refs reaching the event
writers look like `PLAT-123` or `EXT-45` as often as this project's own
shape. Normalization used to strip one hardcoded prefix, which silently
dropped every other project's item id from the indexed integer column.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.events_crud import (
    decompose_work_unit,
    normalize_event_item_id,
)


@pytest.mark.parametrize(
    "ref, expected",
    [
        ("YOK-1907", "1907"),
        ("PLAT-123", "123"),
        ("EXT-45", "45"),
        ("A-7", "7"),
        ("yok-1907", "1907"),
        ("plat-123", "123"),
        ("42", "42"),
        ("PLAT-007", "7"),
    ],
)
def test_any_project_prefix_normalizes_to_the_bare_id(ref, expected) -> None:
    assert normalize_event_item_id(ref) == expected


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
    """Widening the prefix must not swallow non-item work units.

    Each of these keeps a non-numeric tail once an alphabetic prefix comes
    off (or has no prefix at all), so the digit gate still rejects them.
    """
    assert normalize_event_item_id(value) is None


def test_decompose_keeps_epic_task_and_sentinel_routing() -> None:
    assert decompose_work_unit("PLAT-123") == ("123", None, None)
    assert decompose_work_unit("epic-1318-task-3") == ("1318", 3, None)
    assert decompose_work_unit("run-20260417-002") == (
        None,
        None,
        "run-20260417-002",
    )
    assert decompose_work_unit("STRATEGIZE") == (None, None, "STRATEGIZE")
