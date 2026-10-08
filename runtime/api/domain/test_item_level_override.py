"""The ``level`` item-posture override: validation, amendment, and reading."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.item_level_override import (
    LevelOverrideError,
    describe_level_override,
    resolve_level_override,
)
from yoke_core.domain.item_posture_amend import amend_item_posture
from yoke_core.domain.item_posture_amend_guards import ItemPostureAmendError


def _dash(conn, item_id: int) -> int:
    row = insert_item(conn, id=item_id, workflow_id="dash", status="idea")
    return int(row["id"])


def _stored(conn, item_id: int) -> dict:
    raw = conn.execute(
        "SELECT workflow_posture FROM items WHERE id=%s", (item_id,)
    ).fetchone()[0]
    return json.loads(raw) if isinstance(raw, str) else dict(raw or {})


def _amend(conn, item_id: int, value=None, *, clear: bool = False) -> dict:
    return amend_item_posture(
        conn,
        item_id=item_id,
        key="level",
        value=value,
        clear=clear,
        reason="steering staffing default",
    )


def test_amend_stores_a_normalized_override_and_clears_it() -> None:
    with test_database() as conn:
        item_id = _dash(conn, 2901)

        result = _amend(
            conn, item_id, {"shift": -1, "max": "senior", "reason": " routine "}
        )

        stored = {"shift": -1, "max": "SENIOR", "reason": "routine"}
        assert result["changed"] is True
        assert _stored(conn, item_id)["level"] == stored

        _amend(conn, item_id, clear=True)
        assert "level" not in _stored(conn, item_id)


def test_min_and_max_bound_the_override_in_level_order() -> None:
    with test_database() as conn:
        item_id = _dash(conn, 2902)
        _amend(conn, item_id, {"min": "JUNIOR", "max": "PRINCIPAL", "reason": "r"})
        assert _stored(conn, item_id)["level"]["min"] == "JUNIOR"

        with pytest.raises(ItemPostureAmendError, match="min PRINCIPAL is above max"):
            _amend(conn, item_id, {"min": "PRINCIPAL", "max": "JUNIOR", "reason": "r"})


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({"max": "STAFF", "reason": "r"}, "not a level this project reads"),
        ({"max": "SENIOR"}, "requires a non-empty reason"),
        ({"reason": "r"}, "at least one of shift, min, or max"),
        ({"shift": 0, "reason": "r"}, "non-zero integer"),
        ({"shift": True, "reason": "r"}, "non-zero integer"),
        ({"max": "SENIOR", "reason": "r", "level": "X"}, "unknown keys"),
        ("SENIOR", "must be an object"),
    ],
)
def test_malformed_override_refuses_naming_the_correction(value, message) -> None:
    with test_database() as conn:
        item_id = _dash(conn, 2903)
        with pytest.raises(ItemPostureAmendError, match=message):
            _amend(conn, item_id, value)
        assert "level" not in _stored(conn, item_id)


def test_override_reads_as_one_line() -> None:
    posture = {"level": {"shift": 1, "min": "JUNIOR", "reason": "hard bug"}}
    assert describe_level_override(posture) == "level shift +1 · min JUNIOR (hard bug)"
    assert describe_level_override({}) == ""
    assert describe_level_override(None) == ""


@pytest.mark.parametrize(
    ("baseline", "override", "expected"),
    [
        ("SENIOR", None, "SENIOR"),
        ("SENIOR", {"shift": -1}, "JUNIOR"),
        ("JUNIOR", {"shift": 1}, "SENIOR"),
        ("PRINCIPAL", {"max": "SENIOR"}, "SENIOR"),
        ("INTERN", {"min": "SENIOR"}, "SENIOR"),
        ("SENIOR", {"shift": -100}, "INTERN"),
        ("JUNIOR", {"shift": 100}, "PRINCIPAL"),
        ("SENIOR", {"shift": -2, "min": "JUNIOR", "max": "SENIOR"}, "JUNIOR"),
        ("INTERN", {"shift": 3, "min": "JUNIOR", "max": "SENIOR"}, "SENIOR"),
    ],
)
def test_default_level_resolution_applies_shift_then_bounds(
    baseline, override, expected
):
    with test_database() as conn:
        project_id = int(_dash_project(conn))
        value = {**override, "reason": "stage staffing"} if override else None
        result = resolve_level_override(
            conn, project_id=project_id, baseline_level=baseline, override=value
        )
        assert result["baseline_level"] == baseline
        assert result["level"] == expected
        assert result["override"] == (value or {})
        assert result["glyph"] and result["baseline_glyph"]


def _dash_project(conn) -> int:
    row = insert_item(conn, id=2904, workflow_id="dash", status="idea")
    return int(row["project_id"])


def test_default_level_resolution_refuses_invalid_stored_override() -> None:
    with test_database() as conn:
        with pytest.raises(LevelOverrideError, match="min PRINCIPAL is above max"):
            resolve_level_override(
                conn,
                project_id=_dash_project(conn),
                baseline_level="SENIOR",
                override={"min": "PRINCIPAL", "max": "JUNIOR", "reason": "invalid"},
            )
