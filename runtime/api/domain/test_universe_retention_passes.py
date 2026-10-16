"""Pass deadlines, table limits, fixed cutoffs and one-run completion."""

from datetime import timedelta

import pytest

from runtime.api.fixtures.backlog import insert_event
from runtime.api.fixtures.pg_testdb import connect_test_database
from runtime.api.fixtures.universe_prune import cli_on
from yoke_cli.commands.adapters import universe_retention as cli
from yoke_contracts.timestamps import utc_now
from yoke_contracts.universe_retention import PruneRequest, RetentionPolicy
from yoke_core.domain import universe_retention as retention
from yoke_core.domain import universe_retention_pass as passes


def _policy(conn, **fields):
    retention.seed_defaults(conn)
    conn.execute(
        "UPDATE universe_settings SET value=%s WHERE key='retention'",
        (RetentionPolicy(**fields).model_dump_json(),),
    )
    conn.commit()


def _old_events(conn, count, created_at=None):
    created_at = created_at or utc_now() - timedelta(days=2)
    for index in range(count):
        insert_event(
            conn, event_id=f"old-{index}", severity="DEBUG", created_at=created_at
        )
    conn.commit()


def _old_count(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_id LIKE 'old-%%'"
    ).fetchone()[0]


def _next(result, apply=True):
    return PruneRequest(
        apply=apply,
        cutoff=result["cutoff"],
        expected_digest=result["policy_digest"],
        table_index=result["next_table_index"],
    )


def test_pass_deadline_mid_table_resumes_same_table(test_db, monkeypatch):
    _policy(test_db, batch_rows=2)
    _old_events(test_db, 5)
    real = passes._table_pass
    calls = []

    def clipped(conn, policy, deadline, rule, apply):
        calls.append(rule.table)
        if len(calls) == 2:
            # The second cohort of a pass runs on the remaining budget.
            raise TimeoutError("retention_pass_budget")
        return real(conn, policy, deadline, rule, apply)

    monkeypatch.setattr(passes, "_table_pass", clipped)
    first = passes.prune_pass(test_db, PruneRequest(apply=True))
    assert first["failure"] is None and first["skipped"] == []
    assert first["next_table_index"] == 0 and not first["cycle_complete"]
    assert [row["deleted"] for row in first["tables"]] == [{"events": 2}]
    monkeypatch.setattr(passes, "_table_pass", real)
    resumed = passes.prune_pass(test_db, _next(first))
    events = [row for row in resumed["tables"] if row["table"] == "events"]
    assert [row["deleted"]["events"] for row in events] == [2, 1]
    assert resumed["cycle_complete"] and _old_count(test_db) == 0


def test_table_lock_timeout_skips_table_and_continues(test_db, monkeypatch, capsys):
    _policy(test_db, lock_seconds=0.2)
    _old_events(test_db, 3)
    cli_on(test_db, monkeypatch)
    with connect_test_database(test_db.info.dbname) as holder:
        holder.execute("LOCK TABLE api_token_audit IN ACCESS EXCLUSIVE MODE")
        assert cli.universe_prune(["--apply"]) == 0
        holder.rollback()
    out = capsys.readouterr().out
    assert _old_count(test_db) == 0
    assert "Deleted 3 rows" in out
    assert "api_token_audit (retention_table_limit, 3 attempts)" in out
    assert "Recovery: Other tables continued." in out


def test_apply_loops_until_backlog_exhausted(test_db, monkeypatch, capsys):
    _policy(test_db, batch_rows=3)
    _old_events(test_db, 17)
    cli_on(test_db, monkeypatch)
    assert cli.universe_prune(["--apply"]) == 0
    captured = capsys.readouterr()
    assert _old_count(test_db) == 0
    lines = captured.out.splitlines()
    assert lines[0].startswith("Deleted 17 rows in ")
    assert lines[1].split() == ["events", "17"]
    assert "policy" not in captured.out and "Not finished" not in captured.out
    assert captured.err.startswith("Pruning universe ")


def test_fixed_cutoff_ignores_rows_expiring_mid_run(test_db):
    _policy(test_db)
    cutoff = utc_now() - timedelta(seconds=30)
    # Older than one day at the current clock, not at the run's fixed cutoff.
    _old_events(
        test_db, 2, created_at=cutoff - timedelta(days=1) + timedelta(seconds=1)
    )
    request = PruneRequest(apply=True, cutoff=cutoff)
    while True:
        result = passes.prune_pass(test_db, request)
        assert result["failure"] is None
        if result["cycle_complete"]:
            break
        request = _next(result)
    assert _old_count(test_db) == 2
    fresh = passes.prune_pass(test_db, PruneRequest(apply=True))
    assert fresh["tables"][0]["deleted"] == {"events": 2}


def test_unknown_skip_table_refuses(test_db):
    _policy(test_db)
    with pytest.raises(ValueError, match="^retention_table_index_invalid:"):
        passes.prune_pass(test_db, PruneRequest(skip_tables=["not_a_table"]))
