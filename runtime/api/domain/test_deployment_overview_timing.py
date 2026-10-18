"""Overview diagnostics preserve row protocols, failures and request isolation."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yoke_core.domain import deployment_overview_timing as timing
from yoke_core.domain.deployment_start_timing import PREFIX


def _records(capsys):
    output = capsys.readouterr()
    assert not output.out
    return [json.loads(line.removeprefix(PREFIX)) for line in output.err.splitlines()]


def _request(relevance="overview"):
    return SimpleNamespace(payload={"relevance": relevance}, request_id="read-request")


def test_component_capture_keeps_results_and_omits_private_data(capsys, monkeypatch):
    ticks = iter(range(100))
    monkeypatch.setattr(timing, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(timing, "trace_context", lambda: {"trace_id": "trace"})
    cursor = Mock()
    cursor.fetchall.return_value = [{"value": "private-row"}]
    cursor.fetchone.side_effect = [None]
    conn = Mock()
    conn.execute.return_value = cursor

    @timing.overview_phase("qa_acceptance")
    def qa():
        counted = timing.overview_connection(conn)
        result = counted.execute("private SQL", ("private parameter",)).fetchall()
        assert result == [{"value": "private-row"}]
        assert list(counted.execute("private SQL")) == []
        timing.overview_call("repository_open", lambda: None)
        timing.overview_call("ancestry_compare", lambda: True)

    @timing.timed_overview
    def handler(request):
        qa()
        return SimpleNamespace(result_payload={"rows": [{"member_items": [{}, {}]}]})

    first = handler(_request())
    assert first.result_payload == {"rows": [{"member_items": [{}, {}]}]}
    start, end = _records(capsys)
    assert start["step"] == end["step"] == "shipping_overview"
    assert end["outcome"] == "ok"
    assert (end["run_count"], end["member_count"]) == (1, 2)
    assert end["request_id"] == "read-request" and end["trace_id"] == "trace"
    assert end["component_calls"] == {
        "db_execute": 2,
        "db_fetch": 2,
        "repository_open": 1,
        "ancestry_compare": 1,
        "qa_acceptance": 1,
    }
    assert all(value > 0 for value in end["component_ms"].values())
    assert "private" not in json.dumps([start, end])

    # A later request owns empty counters, never the earlier query count.
    @timing.timed_overview
    def empty(request):
        return SimpleNamespace(result_payload={"rows": []})

    empty(_request())
    assert _records(capsys)[-1]["component_calls"] == {}
    assert timing.overview_connection(conn) is conn


def test_failed_db_read_still_refuses_and_records_failed_timing(capsys):
    conn = Mock()
    conn.execute.side_effect = ValueError("unreadable rows")

    @timing.timed_overview
    def handler(request):
        return timing.overview_connection(conn).execute("private SQL")

    with pytest.raises(ValueError, match="unreadable rows"):
        handler(_request())
    end = _records(capsys)[-1]
    assert end["outcome"] == "failed"
    assert end["component_calls"] == {"db_execute": 1}
    assert "unreadable rows" not in json.dumps(end)
    assert timing.overview_connection(conn) is conn


def test_other_reads_and_broken_diagnostic_sink_do_not_change_result(
    capsys, monkeypatch
):
    expected = SimpleNamespace(result_payload={"rows": []})

    @timing.timed_overview
    def handler(request):
        return expected

    assert handler(_request(None)) is expected
    assert _records(capsys) == []
    monkeypatch.setattr(timing, "emit_records", Mock(side_effect=OSError("closed")))
    assert handler(_request()) is expected
    assert timing._COMPONENTS.get() is None


def test_registered_overview_measures_real_composition(test_db, capsys):
    from unittest.mock import patch
    from runtime.api.domain.test_deployment_qa_stage_execution import (
        _plan,
        _seed_run,
        _stages,
    )
    from runtime.api.domain.handlers.deployment_handler_test_support import (
        deployment_request,
    )
    from yoke_core.domain.handlers.deployment_runs import handle_deployment_run_list
    from runtime.api.domain.test_deployment_shipping_reads import CountedConnection

    _seed_run(
        test_db,
        run_id="measured-overview",
        stages=_stages(_plan(test_db)),
        members=(25001,),
    )
    conn = CountedConnection(test_db)
    with patch("yoke_core.domain.deployment_run_list_read.connect", return_value=conn):
        outcome = handle_deployment_run_list(
            deployment_request(
                function="deployment_runs.list",
                payload={"relevance": "overview"},
            )
        )
    assert outcome.primary_success
    records = _records(capsys)
    end = records[-1]
    assert end["component_calls"]["db_execute"] == sum(conn.queries.values())
    assert end["component_calls"]["db_fetch"] > 0
    assert end["component_calls"]["qa_obligations"] == 1
    assert end["component_calls"]["qa_acceptance"] == 1
    assert end["run_count"] == len(outcome.result_payload["rows"])
    assert "start_timings" not in outcome.result_payload
