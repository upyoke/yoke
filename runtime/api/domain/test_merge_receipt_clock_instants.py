"""Local and relayed merge receipts retain one native clock contract."""

from datetime import timedelta, timezone

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain.merge_queue_landing_outcome import recorded_landing
from yoke_core.domain.merge_queue_landing_pending import mark_landing_pending

INSTANT = parse_instant("1969-12-31T23:59:59.123456Z")


def response(function, result):
    return FunctionCallResponse(
        success=True, function=function, version="v1", result=result
    )


@pytest.mark.parametrize(
    "clock",
    [
        INSTANT,
        INSTANT.astimezone(timezone(timedelta(hours=5, minutes=30))),
        "1970-01-01T05:29:59.123456+05:30",
    ],
)
def test_recorded_landing_parses_actual_response_clock(clock):
    def dispatch(*, function_id, target, payload):
        return response(
            function_id,
            {"item": {"merge_queue": {"pr_number": "42", "landed_at": clock}}},
        )

    assert recorded_landing(dispatch, "ITEM-101") == ("42", INSTANT)


def test_recorded_landing_absence_stays_null():
    def dispatch(*, function_id, target, payload):
        return response(
            function_id,
            {"item": {"merge_queue": {"pr_number": "42", "landed_at": None}}},
        )

    assert recorded_landing(dispatch, "ITEM-101") == ("42", None)


@pytest.mark.parametrize("clock", [INSTANT, "1970-01-01T05:29:59.123456+05:30"])
@pytest.mark.parametrize("native_result", [True, False])
def test_preserved_episode_formats_payload_and_returns_native_clock(
    clock, native_result
):
    writes = []

    def dispatch(*, function_id, target, payload):
        if function_id == "items.detail.get":
            return response(
                function_id,
                {"item": {"merge_queue": {"pr_number": "42", "enqueued_at": clock}}},
            )
        writes.append(payload)
        return response(
            function_id,
            {"enqueued_at": INSTANT if native_result else format_instant(INSTANT)},
        )

    assert mark_landing_pending(
        "ITEM-101",
        "42",
        dispatch=dispatch,
        now=INSTANT + timedelta(days=1),
        preserve_existing=True,
    ) == (INSTANT, "")
    assert writes == [{"pr_number": "42", "enqueued_at": format_instant(INSTANT)}]


@pytest.mark.parametrize(
    "clock", ["then", "1970-01-01T00:00:00", "1970-01-01T00:00:00-00:00"]
)
def test_ambiguous_preserved_episode_refuses_before_write(clock):
    calls = []

    def dispatch(*, function_id, target, payload):
        calls.append(function_id)
        return response(
            function_id,
            {"item": {"merge_queue": {"pr_number": "42", "enqueued_at": clock}}},
        )

    with pytest.raises(ValueError):
        mark_landing_pending(
            "ITEM-101", "42", dispatch=dispatch, now=INSTANT, preserve_existing=True
        )
    assert calls == ["items.detail.get"]


@pytest.mark.parametrize(
    "clock",
    [
        "1969-12-31T23:59:59.123456Z",
        "1970-01-01T05:29:59.123456+05:30",
        "",
        "1969-12-31",
        INSTANT.replace(tzinfo=None),
    ],
)
def test_injected_episode_requires_native_clock_before_any_dispatch(clock):
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        raise AssertionError("non-Native clock must refuse before any dispatch")

    with pytest.raises(InvalidInstant):
        mark_landing_pending(
            "ITEM-101", "42", dispatch=dispatch, now=clock, preserve_existing=True
        )
    assert calls == []
