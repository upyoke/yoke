"""Overview state and momentum projection contracts."""

from unittest.mock import patch

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.overview_vitals import handle_overview_vitals


def _request(payload=None):
    return FunctionCallRequest(
        function="overview.vitals.get",
        actor=ActorContext(actor_id="2", session_id=""),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


def test_vitals_returns_closed_state_buckets_and_dense_days():
    class _Connection:
        def close(self):
            pass

    with (
        patch(
            "yoke_core.domain.db_helpers.connect",
            return_value=_Connection(),
        ),
        patch(
            "yoke_core.domain.handlers.overview_vitals._selected_project_ids",
            return_value=[1],
        ),
        patch(
            "yoke_core.domain.handlers.overview_vitals._state_counts",
            return_value={
                "active": 2,
                "pipeline": 3,
                "backlog": 4,
                "blocked": 1,
                "frozen": 0,
                "done": 8,
                "unknown": 0,
            },
        ),
        patch(
            "yoke_core.domain.handlers.overview_vitals._day_counts",
            return_value={},
        ),
        patch(
            "yoke_core.domain.handlers.overview_vitals._strategy_timelines",
            return_value=[
                {
                    "project_id": 1,
                    "project": "yoke",
                    "emoji": "🐄",
                    "done_positions": [10, 80],
                    "labels": [{"position": 10, "label": "registry"}],
                    "queued_count": 2,
                    "vision_zones": [{"key": "1mo", "label": "web steering"}],
                }
            ],
        ),
    ):
        outcome = handle_overview_vitals(_request({"days": 3}))

    assert outcome.primary_success
    assert outcome.result_payload["state_counts"]["active"] == 2
    assert len(outcome.result_payload["momentum"]) == 3
    assert all(
        set(row) == {"day", "activity", "code", "issues", "strategy"}
        for row in outcome.result_payload["momentum"]
    )
    assert outcome.result_payload["strategy_timeline"][0]["queued_count"] == 2


def test_vitals_rejects_unbounded_window():
    outcome = handle_overview_vitals(_request({"days": 366}))
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"


def test_vitals_uses_the_authenticated_actors_visible_projects():
    from yoke_core.domain.handlers.overview_vitals import _visible_project_ids

    request = _request()
    conn = object()
    with patch(
        "yoke_core.domain.actor_project_visibility.actor_visible_project_ids",
        return_value={9, 3},
    ) as visible:
        result = _visible_project_ids(request, conn)

    assert result == [3, 9]
    visible.assert_called_once_with(conn, 2)


def test_vitals_executes_against_initialized_authority(test_db):
    outcome = handle_overview_vitals(_request({"days": 2}))
    assert outcome.primary_success
    assert len(outcome.result_payload["momentum"]) == 2
    assert {
        "active",
        "pipeline",
        "backlog",
        "blocked",
        "frozen",
        "done",
    }.issubset(outcome.result_payload["state_counts"])
    assert isinstance(outcome.result_payload["strategy_timeline"], list)
