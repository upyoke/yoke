"""Where a plan case sits in its plan, and who says so."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_catalog_test_support import CATALOG_CASES
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    create_plan,
    replace_plan_cases,
)


def test_cases_without_a_position_take_their_list_order() -> None:
    """Authoring order is a position; restating it is a transcription step."""
    with test_database() as conn:
        plan = create_plan(
            conn,
            project="yoke",
            slug="implied-order",
            name="Implied order",
            description="Positions come from the list.",
        )
        cases = [
            {key: value for key, value in case.items() if key != "position"}
            for case in CATALOG_CASES
        ]
        replace_plan_cases(conn, plan_id=plan["id"], cases=cases)
        stored = conn.execute(
            "SELECT case_key, position FROM qa_plan_cases "
            "WHERE plan_id=%s ORDER BY position",
            (plan["id"],),
        ).fetchall()
        assert [
            (str(row["case_key"]), int(row["position"])) for row in stored
        ] == [("backend-suite", 1), ("checkout-flow", 2)]


def test_an_explicit_zero_position_is_still_refused() -> None:
    """Defaulting fills an absent position; it does not accept an invalid one."""
    with test_database() as conn:
        plan = create_plan(
            conn,
            project="yoke",
            slug="zero-position",
            name="Zero position",
            description="An explicit 0 is not an omission.",
        )
        cases = [{**CATALOG_CASES[0], "position": 0}]
        with pytest.raises(QaPlanError, match="case position 0"):
            replace_plan_cases(conn, plan_id=plan["id"], cases=cases)
