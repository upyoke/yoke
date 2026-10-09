"""Native Performance grouping and exact owned response clocks."""

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from yoke_contracts.timestamps import format_instant, parse_instant

START = parse_instant("2060-10-08T00:00:00.123456Z")
END = START + timedelta(seconds=120, microseconds=1)
OPAQUE = "2060-10-08T00:00:00+09:00 unchanged"


@pytest.mark.parametrize("zone", ["UTC", "America/Los_Angeles", "Asia/Kathmandu"])
def test_real_event_range_groups_native_microseconds_and_half_open_edges(test_db, zone):
    from runtime.api.auth_test_helpers import mint_api_auth_context
    from runtime.api.fixtures.backlog import insert_event
    from yoke_core.domain.performance_metrics import aggregate
    from yoke_core.domain.performance_query import read_observations

    test_db.execute("SELECT set_config('TimeZone', %s, true)", (zone,))
    auth = mint_api_auth_context(test_db)
    clocks = [
        START - timedelta(microseconds=1),
        START,
        START + timedelta(seconds=60, microseconds=-1),
        START + timedelta(seconds=60),
        END - timedelta(microseconds=1),
        END,
    ]
    for index, clock in enumerate(clocks):
        insert_event(
            test_db,
            event_id=f"performance-edge-{index}",
            event_name="YokeFunctionCalled",
            project_id=auth.project_id,
            duration_ms=index,
            created_at=clock,
        )
    values = read_observations(test_db, auth.actor_id, [auth.project_id], START, END)
    assert {v["event_id"] for v in values} == {
        f"performance-edge-{i}" for i in range(1, 5)
    }
    assert all(isinstance(v["observed_at"], datetime) for v in values)
    assert all("timestamp" not in v for v in values)
    result = aggregate(values, START, END, 20)
    assert result["bucket_seconds"] == 60
    assert [b["metrics"]["function"]["count"] for b in result["buckets"]] == [2, 1, 1]
    assert result["buckets"][-1]["end"] == END
    assert result["last_observation"] == END - timedelta(microseconds=1)
    assert result["buckets"][0]["start"].microsecond == 123456


def test_bucket_resolution_rounds_up_without_float_instant_loss():
    from yoke_core.domain.performance_metrics import aggregate, bucket_seconds

    until = START + timedelta(minutes=20, microseconds=1)
    assert bucket_seconds(START, until, 20) == 120
    assert len(aggregate([], START, until, 20)["buckets"]) == 11
    assert aggregate([], START, until, 20)["last_observation"] is None
    shifted = START.astimezone(timezone(timedelta(hours=5, minutes=45)))
    assert aggregate([], shifted, END, 20)["buckets"][0]["start"] == START


@pytest.mark.parametrize("model", ["PerformanceRequest", "PerformanceDetailRequest"])
@pytest.mark.parametrize(
    "invalid",
    [
        0,
        1.5,
        True,
        "",
        "2060-10-08",
        "2060-10-08T00:00:00",
        "2060-10-08T00:00:00-00:00",
        datetime(2060, 10, 8),
    ],
)
def test_range_ingress_rejects_coercion_and_unqualified_clocks(model, invalid):
    from yoke_core.domain.handlers import performance_reads as handlers

    with pytest.raises(ValueError):
        getattr(handlers, model).model_validate(
            {"since": invalid, "until": format_instant(END)}
        )


@pytest.mark.parametrize("detail", [False, True])
def test_handler_formats_only_native_response_clocks(monkeypatch, detail):
    from yoke_core.domain.handlers import performance_reads as handlers
    from yoke_core.domain.performance_observations import observation

    source = observation(
        {
            "event_id": OPAQUE,
            "created_at": START,
            "event_name": "YokeFunctionCalled",
            "duration_ms": 0,
            "command_summary": OPAQUE,
            "envelope": {"context": {"function": OPAQUE}},
        },
        END,
    )
    seen = []

    def read(conn, actor, projects, start, end):
        seen.append((start, end))
        return [source]

    monkeypatch.setattr(handlers, "connect", lambda: nullcontext(object()))
    monkeypatch.setattr(handlers, "read_observations", read)
    monkeypatch.setattr(handlers, "utc_now", lambda: END)
    request = SimpleNamespace(
        payload={
            "since": "2060-10-08T05:45:00.123456+05:45",
            "until": format_instant(END),
            "points": 20,
        },
        actor=SimpleNamespace(actor_id=None),
    )
    outcome = (handlers.handle_detail if detail else handlers.handle_aggregate)(request)
    assert outcome.primary_success
    assert seen == [(START, END)]
    result = outcome.result_payload
    if detail:
        result_row = result["rows"][0]
        assert result_row["observed_at"] == format_instant(START)
        assert (
            result_row["event_id"]
            == result_row["operation"]
            == result_row["command_summary"]
            == OPAQUE
        )
        assert result_row["trace_id"] is None
        assert "timestamp" not in result_row
    else:
        assert result["buckets"][0]["start"] == format_instant(START)
        assert result["buckets"][-1]["end"] == format_instant(END)
        assert result["queried_at"] == format_instant(END)
        assert result["last_observation"] == format_instant(START)
    assert source["observed_at"] is START


@pytest.mark.parametrize("detail", [False, True])
def test_reversed_range_refuses_before_connection(monkeypatch, detail):
    from yoke_core.domain.handlers import performance_reads as handlers

    monkeypatch.setattr(
        handlers, "connect", lambda: pytest.fail("range must refuse before SQL")
    )
    request = SimpleNamespace(
        payload={"since": format_instant(END), "until": format_instant(START)},
        actor=SimpleNamespace(actor_id=None),
    )
    outcome = (handlers.handle_detail if detail else handlers.handle_aggregate)(request)
    assert not outcome.primary_success
    assert outcome.error.code == "performance_range_invalid"


def test_actual_review_page_filters_captured_microsecond_edges():
    import json
    import subprocess
    from pathlib import Path
    from runtime.api.tools.serve_performance_review import PAGE

    script = PAGE.split('<script type="module">', 1)[1].split("</script>", 1)[0]
    kernel = (
        Path(__file__).resolve().parents[2]
        / "packages/yoke-core/src/yoke_core/ui/static/timestamps.js"
    )
    script = script.replace(
        "import {renderPerformanceView} from '/static/universe_views_performance.js';",
        "const renderPerformanceView = () => {};",
    )
    script = script.replace("'/static/timestamps.js'", json.dumps(kernel.as_uri()))
    setup = """
import assert from 'node:assert/strict';
const values = ['2060-10-08T00:00:00.123455Z', '2060-10-08T00:00:00.123456Z',
                '2060-10-08T05:45:00.123456+05:45', '2060-10-08T00:00:00.123457Z'];
const receipts = {'/aggregate': {result: {observation_count: 4, queried_at: values[0]}},
                  '/detail': {result: {rows: values.map((observed_at, id) => ({id, observed_at, family: 'function'}))}}};
globalThis.fetch = async path => ({json: async () => receipts[path], text: async () => 'candidate'});
globalThis.document = {querySelector: () => ({})};
"""
    check = """
const response = await client.call({function: 'events.performance.detail', payload: {
 since: '2060-10-08T00:00:00.123456Z', until: '2060-10-08T00:00:00.123457Z', family: 'function'}});
assert.deepEqual(response.envelope.result.rows.map(row => row.id), [1, 2]);
"""
    result = subprocess.run(
        ["node", "--input-type=module"],
        input=setup + script + check,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
