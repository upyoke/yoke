"""Message and signing owners reject ambiguous clocks before side effects."""

from importlib import import_module

import pytest

from runtime.api.domain.test_provided_clock_ingress import (
    BAD_CLOCKS,
    INSTANT,
    UntouchedConnection,
    unused_clock,
)
from runtime.api.domain.test_session_message_support import selector
from yoke_contracts.timestamps import InvalidInstant, format_instant

OWNERS = (
    (
        "session_message_selectors",
        "resolve_recipients",
        {"selector": selector(session_ids=["sample"])},
    ),
    (
        "session_message_service",
        "preview_message",
        {"actor_id": 1, "selector": selector(session_ids=["sample"])},
    ),
    (
        "session_message_service",
        "send_message",
        {
            "actor_id": 1,
            "sender_session_id": "sample",
            "selector": selector(session_ids=["sample"]),
            "body": "sample",
        },
    ),
    (
        "session_message_delivery_probe",
        "record_undelivered_receipts",
        {"session_id": "sample", "hook_event": "PostToolUse", "reason": "pending"},
    ),
    (
        "session_broker_wake_fallback",
        "direct_wake_waits_for_broker",
        {"message_id": "sample", "session_id": "sample"},
    ),
    ("session_message_wake", "wake_eligible_recipients", {}),
    (
        "deployment_qa_stage_wake_withdraw",
        "withdraw_deployment_qa_wait_wakes",
        {"run_id": "run"},
    ),
    ("session_message_delivery", "expire_due_recipients", {}),
    (
        "session_message_receipts",
        "acknowledge_message",
        {"message_id": "sample", "session_id": "sample"},
    ),
    (
        "session_message_receipts",
        "acknowledge_actor_message",
        {"message_id": "sample", "actor_id": 1},
    ),
    (
        "session_message_receipts",
        "cancel_message",
        {"message_id": "sample", "actor_id": 1},
    ),
    ("actor_message_recipients", "expire_due_actor_recipients", {}),
    (
        "session_surface_policy",
        "set_mark",
        {
            "machine_id": "machine",
            "surface": "codex-cli",
            "reason": "sample",
            "actor_id": 1,
            "session_id": "sample",
        },
    ),
    (
        "session_surface_policy",
        "clear_mark",
        {"machine_id": "machine", "surface": "codex-cli", "actor_id": 1},
    ),
    (
        "session_manual_wake",
        "request_session_wake",
        {
            "actor_id": 1,
            "caller_session_id": "sample",
            "session_id": "sample",
            "public_ref": None,
            "prompt": "sample",
        },
    ),
    ("session_keepalive", "session_keepalive_holds", {"session_ids": ["sample"]}),
)


@pytest.mark.parametrize("clock", BAD_CLOCKS)
@pytest.mark.parametrize("module_name,function_name,arguments", OWNERS)
def test_invalid_message_clock_refuses_before_sql_or_clock_default(
    monkeypatch, module_name, function_name, arguments, clock
):
    owner = import_module(f"yoke_core.domain.{module_name}")
    monkeypatch.setattr(owner, "utc_now", unused_clock)
    arguments = dict(arguments)
    if function_name == "record_undelivered_receipts":
        arguments["reason"] = next(iter(owner.PROBE_REASONS))
    with pytest.raises(InvalidInstant):
        getattr(owner, function_name)(UntouchedConnection(), now=clock, **arguments)


@pytest.mark.parametrize("clock", BAD_CLOCKS)
def test_actor_read_and_launch_delivery_clock_refuse_before_reads(monkeypatch, clock):
    from yoke_core.domain import actor_message_recipients, session_launch_store

    monkeypatch.setattr(actor_message_recipients, "utc_now", unused_clock)
    with pytest.raises(InvalidInstant):
        actor_message_recipients.acknowledge_actor_recipient(
            UntouchedConnection(), message_id="sample", actor_id=1, read_at=clock
        )
    with pytest.raises(InvalidInstant):
        session_launch_store.update_launch(
            UntouchedConnection(),
            "sample",
            delivery_changed_at=clock,
            state="succeeded",
        )


@pytest.mark.parametrize("clock", BAD_CLOCKS)
def test_github_signing_and_cache_refuse_bad_clock_before_custody_or_transport(
    monkeypatch, clock
):
    from yoke_core.domain import (
        github_app_installation_tokens as tokens,
        github_app_jwt,
    )

    for owner in (tokens, github_app_jwt):
        monkeypatch.setattr(owner, "utc_now", unused_clock)
    arguments = dict(issuer="sample", private_key_pem=b"sample", now=clock)
    with pytest.raises(InvalidInstant):
        github_app_jwt.generate_app_jwt(**arguments)
    with pytest.raises(InvalidInstant):
        tokens.mint_installation_token(
            **arguments, installation_id=1, opener=unused_clock
        )
    with pytest.raises(InvalidInstant):
        tokens.InstallationTokenCache().get_or_mint(
            **arguments, installation_id=1, opener=unused_clock
        )


@pytest.mark.parametrize("postgres", (True, False))
@pytest.mark.parametrize("clock", (INSTANT, "2026-10-09T20:45:00.123456+05:45", None))
def test_surface_policy_sql_and_response_clocks_have_distinct_owned_representations(
    monkeypatch, clock, postgres
):
    from yoke_core.domain import session_surface_policy as policy

    monkeypatch.setattr(
        policy, "utc_now", (lambda: INSTANT) if clock is None else unused_clock
    )
    monkeypatch.setattr(policy, "live_mark", lambda *args: None)

    class Connection:
        def __init__(self):
            self.writes = []

        def execute(self, sql, params):
            self.writes.append((sql, params))

    conn = Connection()
    monkeypatch.setattr(policy, "marker", lambda conn: "%s")
    from yoke_core.domain import db_backend

    monkeypatch.setattr(db_backend, "connection_is_postgres", lambda conn: postgres)
    expected_sql = INSTANT if postgres else format_instant(INSTANT)
    created = policy.set_mark(
        conn,
        machine_id="machine",
        surface="codex-cli",
        reason="opaque sample",
        actor_id=1,
        session_id="sample",
        now=clock,
    )
    assert conn.writes[0][1][-1] == expected_sql
    assert created["created_at"] == format_instant(INSTANT)
    assert created["cleared_at"] is None
    monkeypatch.setattr(policy, "live_mark", lambda *args: dict(created))
    cleared = policy.clear_mark(
        conn, machine_id="machine", surface="codex-cli", actor_id=2, now=clock
    )
    assert conn.writes[-1][1][0] == expected_sql
    assert cleared["cleared_at"] == format_instant(INSTANT)
    assert cleared["reason"] == "opaque sample"
    raw = dict(created, created_at=INSTANT, cleared_at=INSTANT)
    assert policy._row(raw)["created_at"] == format_instant(INSTANT)
    assert policy._row(raw)["cleared_at"] == format_instant(INSTANT)
