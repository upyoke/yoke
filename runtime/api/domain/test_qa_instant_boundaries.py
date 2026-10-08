"""Native QA ordering and exact authority, health, age and debug boundaries."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement, insert_qa_run
from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.api.observability_debug import (
    DEBUG_SCOPE_ENV,
    DEBUG_UNTIL_ENV,
    parse_debug_campaign,
)
from yoke_core.domain import qa_start_bound_authority as authority
from yoke_core.domain.qa_gate_summary import _format_run
from yoke_core.domain.qa_latest_execution import (
    latest_execution_id_sql,
    latest_executions,
)
from yoke_core.domain.overview_harness_hook_health import (
    HOOK_TELEMETRY_WINDOW,
    STATUS_ACTIVE,
    STATUS_INSTALLED_LAST_SEEN,
    harness_targets,
)
from yoke_core.domain.time_parse import (
    age_hours_since,
    age_minutes_since,
    parse_timestamp_utc,
)


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_actual_start_order_and_wire_summary_are_timezone_invariant(test_db, zone):
    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    epoch = parse_instant("1969-12-31T23:59:59.999998Z")
    requirement = insert_qa_requirement(test_db, created_at=epoch)
    newest = insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        verdict=None,
        started_at=epoch + timedelta(microseconds=1),
        created_at=epoch,
    )
    older = insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        verdict="pass",
        started_at=epoch,
        created_at=epoch + timedelta(days=1),
    )
    assert older["id"] > newest["id"]
    selected = latest_executions(test_db, [requirement["id"]])[requirement["id"]]
    assert selected["id"] == newest["id"]
    assert selected["started_at"] == epoch + timedelta(microseconds=1)
    assert _format_run(selected)["created_at"] == format_instant(epoch)
    sql = latest_execution_id_sql("%s")
    assert test_db.execute(sql, (requirement["id"],)).fetchone()[0] == newest["id"]
    equal = insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        verdict="fail",
        started_at=newest["started_at"],
        created_at=epoch,
    )
    assert (
        latest_executions(test_db, [requirement["id"]])[requirement["id"]]["id"]
        == equal["id"]
    )
    assert test_db.execute(sql, (requirement["id"],)).fetchone()[0] == equal["id"]
    ambiguous = insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        verdict=None,
        started_at=None,
        created_at=epoch,
    )
    assert test_db.execute(sql, (requirement["id"],)).fetchone()[0] == ambiguous["id"]
    with pytest.raises(ValueError, match="qa_execution_order_ambiguous"):
        latest_executions(test_db, [requirement["id"]])


def test_authority_health_age_and_debug_keep_exact_microsecond_windows():
    now = parse_instant("1969-12-31T23:59:59.999999Z")
    released = now - timedelta(seconds=authority.AUTHORITY_WINDOW_SECONDS)
    for delta, expected in [(timedelta(), True), (timedelta(microseconds=-1), False)]:
        with patch.object(
            authority, "_claim_row", return_value=("session", 1, released + delta)
        ):
            assert (
                authority.start_bound_claim_grants(
                    1, session_id="session", item_id=1, now=now
                )
                is expected
            )
    seen = now - HOOK_TELEMETRY_WINDOW
    for delta, expected in [
        (timedelta(), STATUS_ACTIVE),
        (timedelta(microseconds=-1), STATUS_INSTALLED_LAST_SEEN),
    ]:
        targets = harness_targets(
            [
                dict(
                    executor="codex",
                    display="codex-cli",
                    hook_fed=1,
                    seen_at=seen + delta,
                )
            ],
            now=now,
        )
        codex = next(row for row in targets if row["key"] == "codex")
        assert codex["status"] == expected
        assert codex["last_seen_at"] == format_instant(seen + delta)
    assert age_hours_since(now - timedelta(hours=1, microseconds=-1), now=now) == 0
    assert age_hours_since(now - timedelta(hours=1), now=now) == 1
    assert age_minutes_since(now - timedelta(minutes=1, microseconds=-1), now=now) == 0
    assert age_minutes_since(now - timedelta(minutes=1), now=now) == 1
    assert age_minutes_since(now + timedelta(microseconds=1), now=now) == 0
    assert age_hours_since(None, now=now) == 0
    assert parse_timestamp_utc(None) is None
    env = {DEBUG_SCOPE_ENV: "request:exact", DEBUG_UNTIL_ENV: format_instant(now)}
    assert parse_debug_campaign(env, now=now) is None
    campaign = parse_debug_campaign(env, now=now - timedelta(microseconds=1))
    assert campaign.until == now
    assert format_instant(now) in campaign.identity


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "1969-12-31",
        "1969-12-31T23:59:59",
        "1969-12-31T23:59:59.1234567Z",
        datetime(1969, 12, 31),
    ],
)
def test_supplied_invalid_instants_are_never_unknown_or_guessed(bad):
    with pytest.raises(InvalidInstant, match="invalid_instant"):
        parse_timestamp_utc(bad)
    with pytest.raises(InvalidInstant):
        age_minutes_since(bad)
    with patch.object(authority, "_claim_row", return_value=("session", 1, bad)):
        with pytest.raises(InvalidInstant):
            authority.start_bound_claim_grants(1, session_id="session", item_id=1)
    with pytest.raises(ValueError, match="qa_execution_order_ambiguous"):
        from yoke_core.domain.qa_latest_execution import execution_start

        execution_start(dict(id=1, started_at=bad))
    if isinstance(bad, str) and bad:
        with pytest.raises(InvalidInstant):
            parse_debug_campaign(
                {DEBUG_SCOPE_ENV: "request:exact", DEBUG_UNTIL_ENV: bad}
            )


def test_naive_current_clock_cannot_authorize_or_classify():
    naive = datetime(1969, 12, 31)
    with pytest.raises(InvalidInstant):
        harness_targets([], now=naive)
    with pytest.raises(InvalidInstant):
        age_hours_since("1969-12-31T00:00:00Z", now=naive)
