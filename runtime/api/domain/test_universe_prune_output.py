"""Concise prune output, progress lines, detail, interruption and skew."""

import io
import json

from yoke_cli.commands.adapters import universe_retention as cli
from yoke_cli.commands.adapters.universe_retention_output import PruneRun
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_contracts.timestamps import utc_now


def _pass(tables, *, cycle_complete=True, skipped=(), **extra):
    result = {
        "universe": {"slug": "example"},
        "source": "default",
        "policy": {"batch_rows": 5000},
        "policy_digest": "digest",
        "cutoff": utc_now().isoformat(),
        "next_table_index": 0,
        "cycle_complete": cycle_complete,
        "skipped": list(skipped),
        "tables": [
            {
                "table": table,
                "deleted": {table: count} if count else {},
                "eligible": count,
                "eligible_partial": partial,
                "protected": None,
                "protected_graphs": 0,
            }
            for table, count, partial in tables
        ],
    }
    result.update(extra)
    return FunctionCallResponse(
        success=True, function="universe.prune.run", version="v1", result=result
    )


def _serve(monkeypatch, responses):
    monkeypatch.setattr(cli, "ensure_handlers_loaded", lambda: None)
    calls = []

    def call(**kwargs):
        calls.append(kwargs)
        reply = responses[len(calls) - 1]
        if isinstance(reply, BaseException):
            raise reply
        return reply

    monkeypatch.setattr(cli, "call_dispatcher", call)
    return calls


SKIP = {
    "table": "session_messages",
    "code": "retention_table_limit",
    "reason": "a statement or lock limit was reached with the full pass budget",
    "recovery": "Other tables continued.",
}


def test_summary_lists_changed_tables_and_unfinished_reason(monkeypatch, capsys):
    calls = _serve(
        monkeypatch,
        [
            _pass(
                [("api_token_audit", 5000, True), ("events", 7, False)],
                cycle_complete=False,
            ),
            _pass(
                [("api_token_audit", 2, False), ("events", 0, False)], skipped=[SKIP]
            ),
            _pass([("api_token_audit", 0, False)], skipped=[SKIP]),
            _pass([], skipped=[SKIP]),
        ],
    )
    assert cli.universe_prune(["--apply"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("Deleted 5,009 rows in ")
    assert out[1].split() == ["api_token_audit", "5,002"]
    assert out[2].split() == ["events", "7"]
    assert out[3] == "Not finished:"
    assert out[4].startswith("  session_messages (retention_table_limit, 3 attempts): ")
    assert len(out) == 5
    assert calls[2]["payload"]["skip_tables"] == ["events"]
    assert calls[3]["payload"]["skip_tables"] == ["api_token_audit", "events"]


def test_full_and_json_keep_per_table_detail(monkeypatch, capsys):
    once = _pass([("events", 3, False)])
    _serve(monkeypatch, [once, _pass([("events", 0, False)]), once])
    assert cli.universe_prune(["--apply", "--full"]) == 0
    out = capsys.readouterr().out
    assert "events: eligible=0; deleted=3" in out
    assert "policy=digest" in out
    assert cli.universe_prune(["--dry-run", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["mode"] == "preview" and result["policy"] == {"batch_rows": 5000}
    assert result["tables"][0]["table"] == "events"


def test_preview_is_one_cycle_with_apply_hint(monkeypatch, capsys):
    calls = _serve(
        monkeypatch, [_pass([("events", 5000, True), ("web_sessions", 0, False)])]
    )
    assert cli.universe_prune([]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("Preview only; nothing deleted")
    assert out[1:] == [
        "  events: >=5,000 eligible",
        "Rerun with --apply to delete. Add --full for per-table detail.",
    ]
    assert len(calls) == 1


def test_progress_line_names_largest_remaining_table():
    now = [0.0]
    run = PruneRun(True, clock=lambda: now[0])
    run.record(_pass([("events", 40, True), ("api_token_audit", 900, True)]).result)
    stream = io.StringIO()
    run.progress(stream)
    assert stream.getvalue() == ""
    now[0] = 75.0
    run.progress(stream)
    assert stream.getvalue() == (
        "Pruning: 940 rows deleted · largest remaining: api_token_audit · 1m 15s elapsed\n"
    )


def test_interrupt_prints_summary_and_keeps_counts(monkeypatch, capsys):
    _serve(
        monkeypatch,
        [_pass([("events", 4, True)], cycle_complete=False), KeyboardInterrupt()],
    )
    assert cli.universe_prune(["--apply"]) == 130
    captured = capsys.readouterr()
    assert captured.out.startswith("Deleted 4 rows in ")
    assert "retention_interrupted" in captured.err


def test_missing_new_response_field_refuses_with_floor(monkeypatch, capsys):
    reply = _pass([("events", 2, False)])
    del reply.result["skipped"]
    _serve(monkeypatch, [reply])
    assert cli.universe_prune(["--apply", "--json"]) != 0
    result = json.loads(capsys.readouterr().out)
    assert result["error"]["code"] == "retention_response_version_skew"
    assert "floor: next-release" in result["error"]["message"]
    assert result["result"]["deleted"] == {"events": 2}


def test_command_lost_reply_keeps_acknowledged_counts_and_does_not_retry(
    monkeypatch, capsys
):
    lost = FunctionCallResponse(
        success=False,
        function="universe.prune.run",
        version="v1",
        error=FunctionError(code=cli.TRANSPORT_FAILED_CODE, message="lost reply"),
    )
    calls = _serve(
        monkeypatch, [_pass([("events", 5, True)], cycle_complete=False), lost]
    )
    assert cli.universe_prune(["--apply", "--json"]) != 0
    result = json.loads(capsys.readouterr().out)
    assert result["result"]["deleted"] == {"events": 5}
    assert result["error"]["code"] == "retention_pass_outcome_unknown"
    assert len(calls) == 2 and all(c["max_attempts"] == 1 for c in calls)
