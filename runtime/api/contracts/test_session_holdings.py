"""Shared session-holdings grouping contract."""

from __future__ import annotations

import pytest

from yoke_contracts.session_holdings import (
    SESSION_PATH_HOLDING_KEY,
    coordination_holding_key,
    group_session_holdings,
    steering_holding_key,
    strategy_document_holding_key,
    work_holding_key,
)


def _holding(target: str, *, released: str | None) -> dict[str, str | None]:
    return {
        "target_key": target,
        "target": target,
        "released_at": released,
    }


def test_current_target_displaces_all_previous_occurrences() -> None:
    grouped = group_session_holdings(
        [
            _holding("YOK-4", released="2026-08-28T12:00:00Z"),
            _holding("YOK-4", released=None),
            _holding("YOK-4", released="2026-08-27T12:00:00Z"),
        ],
        previous_limit=4,
    )

    assert [row["target"] for row in grouped["current"]] == ["YOK-4"]
    assert grouped["previous"] == []


def test_previous_targets_deduplicate_before_truncation() -> None:
    grouped = group_session_holdings(
        [
            _holding("YOK-3", released="newest"),
            _holding("YOK-3", released="older"),
            _holding("YOK-2", released="old"),
            _holding("YOK-1", released="oldest"),
        ],
        previous_limit=2,
    )

    assert [row["target"] for row in grouped["previous"]] == ["YOK-3", "YOK-2"]
    assert grouped["previous_remainder"] == 1


def test_previous_claims_prioritize_steering_and_keep_latest_release_count() -> None:
    item = {
        "holding_kind": "work_claim",
        "target_kind": "item",
        "target_key": "work:item:3",
        "target": "YOK-3",
    }
    steering = {
        "holding_kind": "work_claim",
        "target_kind": "steering",
        "target_key": "work:steering:1:CURRENT-PLAN",
        "target": "steering yoke",
    }
    grouped = group_session_holdings(
        [
            {**item, "released_at": "2026-08-28T12:00:00Z"},
            {**steering, "released_at": "2026-08-28T11:00:00Z"},
            {**item, "released_at": "2026-08-28T13:00:00Z"},
            {**steering, "released_at": "2026-08-28T12:30:00Z"},
            {**_holding("work:item:2", released="old"), "target_kind": "item"},
        ],
        previous_limit=2,
    )

    assert [row["target"] for row in grouped["previous"]] == [
        "steering yoke",
        "YOK-3",
    ]
    assert [row["released_at"] for row in grouped["previous"]] == [
        "2026-08-28T12:30:00Z",
        "2026-08-28T13:00:00Z",
    ]
    assert [row["occurrence_count"] for row in grouped["previous"]] == [2, 2]
    assert grouped["previous_remainder"] == 1


def test_duplicate_target_facets_merge_into_one_row() -> None:
    grouped = group_session_holdings(
        [
            {**_holding("YOK-8", released=None), "item_title": "Eight"},
            {**_holding("YOK-8", released=None), "path_count": 3},
        ],
        previous_limit=2,
    )

    assert grouped["current"] == [
        {
            "target_key": "YOK-8",
            "target": "YOK-8",
            "released_at": None,
            "item_title": "Eight",
            "path_count": 3,
        }
    ]


def test_released_path_facet_does_not_inflate_work_claim_count() -> None:
    grouped = group_session_holdings(
        [
            {
                **_holding("work:item:8", released="2026-08-28T12:00:00Z"),
                "holding_kind": "work_claim",
            },
            {
                **_holding("work:item:8", released="2026-08-28T12:00:00Z"),
                "holding_kind": "path_claim",
                "path_count": 3,
            },
        ],
        previous_limit=2,
    )

    assert grouped["previous"][0]["path_count"] == 3
    assert "occurrence_count" not in grouped["previous"][0]


def test_previous_limit_is_a_required_render_parameter() -> None:
    with pytest.raises(ValueError, match="render surface's row budget"):
        group_session_holdings([], previous_limit=-1)


def test_observation_without_authority_target_teaches_the_fix() -> None:
    with pytest.raises(ValueError, match="derive it from the authority target"):
        group_session_holdings([{"released_at": None}], previous_limit=1)


def test_authority_target_keys_are_shared_across_render_surfaces() -> None:
    assert work_holding_key("item", item_id=8) == "work:item:8"
    assert work_holding_key("process", process_key="feed") == "work:process:feed"
    assert work_holding_key("steering", project_id=3) == "work:steering:3"
    assert steering_holding_key(3, ["MISSION", "CURRENT-PLAN"]) == (
        "work:steering:3:CURRENT-PLAN,MISSION"
    )
    assert steering_holding_key(3, ["CURRENT-PLAN"]) != (
        steering_holding_key(3, ["MISSION"])
    )
    assert SESSION_PATH_HOLDING_KEY == "path:session"
    assert strategy_document_holding_key(3, "VISION") == ("strategy_document:3:VISION")
    assert coordination_holding_key("QA_HOST:test-mac") == (
        "coordination:QA_HOST:test-mac"
    )
