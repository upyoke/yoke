"""Org-owned receipts share wake policy and keep relay actors isolated."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_org_scope_relay_reports import (
    MACHINE,
    NOW,
    OLD,
    world as world,
)
from runtime.api.domain.session_relay_handler_test_support import (
    NoCloseConnection,
    claim_payload,
    relay_request,
)
from yoke_contracts.timestamps import format_instant
from yoke_contracts.session_control.wake_delivery import NATIVE_RESUME_ACCEPTED_RESULT
from yoke_core.domain import session_broker_wake as broker
from yoke_core.domain import session_message_wake as wake
from yoke_core.domain import session_message_wake_skip as skip
from yoke_core.domain import session_stale_alive_probe as probe
from yoke_core.domain import session_wake_deferral as deferral
from yoke_core.domain import session_wake_reconciliation as reconciliation
from yoke_core.domain import session_operator_wake_notice as operator
from yoke_core.domain import session_wake_failure_notice as failure
from yoke_core.domain import actor_permissions, db_helpers
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.session_message_authorization import scope_policy
from yoke_core.domain.session_message_recipient_scope import (
    actor_reads_recipient,
    owner_key,
    recipient_owner,
    recipient_policy,
)
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_core.domain.handlers import session_relay as relay
from yoke_core.domain.handlers import session_relay_poll_upkeep as upkeep
from yoke_core.domain.handlers.session_relay_idle_hosts import handle_relay_idle_hosts


def receipt(conn, sid="own"):
    session = dict(
        conn.execute(
            "SELECT * FROM harness_sessions WHERE session_id=%s", (sid,)
        ).fetchone()
    )
    conn.execute(
        "INSERT INTO session_messages(message_id,sender_actor_id,body,body_sha256,"
        "selector_snapshot,created_at,expires_at) VALUES ('pending',%s,'hello','sha','{}',%s,%s)",
        (session["actor_id"], OLD, NOW + timedelta(hours=1)),
    )
    conn.execute(
        "INSERT INTO session_message_recipients(message_id,session_id,project_id,org_id,"
        "executor_surface,executor_version,state,resolution_evidence,routing_snapshot,created_at,wake_after) "
        "VALUES ('pending',%s,%s,%s,'codex-cli','1.0','pending','{}','{}',%s,%s)",
        (sid, session["project_id"], session["org_id"], OLD, OLD),
    )
    conn.commit()
    return dict(session, message_id="pending", wake_attempt_count=0, last_wake_at=None)


def test_scope_policy_project_and_org(world):
    conn, _, _ = world
    org = conn.execute("SELECT org_id FROM projects WHERE id=1").fetchone()[0]
    project = scope_policy(conn, project_id=1)
    policy = scope_policy(conn, org_id=org)
    assert project.project_id == 1
    assert policy.project_id is None and policy.org_id == org
    assert policy.wake_ack_grace_seconds == project.wake_ack_grace_seconds
    with pytest.raises(SessionMessageError, match="does not exist") as exc:
        scope_policy(conn, org_id=-1)
    assert exc.value.code == "org_not_found"


@pytest.mark.parametrize("scope", [{}, {"project_id": 1, "org_id": 1}])
def test_scope_policy_rejects_both_and_neither(world, scope):
    with pytest.raises(ValueError, match="exactly one"):
        scope_policy(world[0], **scope)


def test_actor_reads_org_recipient_owner_and_org_operator_only(world):
    conn, owner, foreign = world
    row = dict(
        conn.execute("SELECT * FROM harness_sessions WHERE session_id='own'").fetchone()
    )
    assert recipient_owner(row) == (None, row["org_id"])
    assert actor_reads_recipient(conn, actor_id=owner, row=row)
    assert not actor_reads_recipient(conn, actor_id=foreign, row=row)
    reader = seed_human_actor(conn, "Org reader")
    actor_permissions.grant_actor_org_role(
        conn,
        actor_id=reader,
        org_id=row["org_id"],
        role_name=actor_permissions.ROLE_OPERATOR,
    )
    assert actor_reads_recipient(conn, actor_id=reader, row=row)
    assert owner_key(row) != owner_key({"project_id": row["org_id"], "org_id": None})


def test_broker_wake_org_recipient_policy(world, monkeypatch):
    conn, _, _ = world
    row = dict(receipt(conn), machine_id=MACHINE, wake_mode="waiting")
    monkeypatch.setattr(broker, "wake_eligible_recipients", lambda *a, **kw: [row])
    monkeypatch.setattr(broker, "direct_wake_waits_for_broker", lambda *a, **kw: False)
    assert broker._candidate_routes(conn, broker_session_id="project", now=NOW) == [row]


def test_wake_skip_org(world, monkeypatch):
    conn, _, _ = world
    row = receipt(conn)
    monkeypatch.setattr(skip, "notify_failed_wake", lambda *a, **kw: None)
    skip.record_wake_skip(
        conn, row, operation=None, relay_versions={}, liveness="stale", now=NOW
    )
    assert (
        conn.execute(
            "SELECT wake_attempt_count FROM session_message_recipients"
        ).fetchone()[0]
        == 1
    )
    attempt = conn.execute("SELECT result_code FROM session_message_attempts")
    assert attempt.fetchone()[0].startswith("skipped_")


def test_reconciliation_org_grace(world):
    conn, _, _ = world
    row = receipt(conn)
    conn.execute(
        "INSERT INTO session_message_attempts(attempt_id,message_id,target_session_id,attempt_kind,"
        "started_at,result_code) VALUES ('accepted','pending','own','wake_relay',%s,%s)",
        (OLD, NATIVE_RESUME_ACCEPTED_RESULT),
    )
    assert (
        reconciliation.reconcile_spawned_wake_attempts(conn, now=format_instant(NOW))
        == 1
    )
    assert (
        conn.execute("SELECT result_code FROM session_message_attempts").fetchone()[0]
        == "turn_without_injection"
    )
    cache = {}
    reconciliation._delivery_grace_seconds(conn, row, cache)
    reconciliation._delivery_grace_seconds(
        conn, {"project_id": row["org_id"], "org_id": None}, cache
    )
    assert len(cache) == 2


@pytest.mark.parametrize(
    "projects,actor_name", [([1], "owner"), ([], "owner"), ([1], None)]
)
def test_stale_probe_serves_relay_actor_org_sessions_only(
    world, monkeypatch, projects, actor_name
):
    conn, owner, _ = world
    for sid in ("own", "foreign", "remote", "project"):
        conn.execute(
            "INSERT INTO work_claims(session_id,target_kind,scope,claimed_at,last_heartbeat) "
            "VALUES (%s,'process','{}',%s,%s)",
            (sid, OLD, OLD),
        )
    sent = []
    monkeypatch.setattr(probe, "_send_probe", lambda c, r: sent.append(r["session_id"]))
    result = probe.probe_stale_alive_sessions(
        conn,
        machine_id=MACHINE,
        authorized_projects=projects,
        relay_actor_id=owner if actor_name else None,
        now=NOW,
    )
    expected = ({"project"} if projects else set()) | ({"own"} if actor_name else set())
    assert set(result["probed"]) == expected == set(sent)


def test_wake_deferral_org_backoff(world):
    conn, _, _ = world
    row = receipt(conn)
    conn.execute("UPDATE session_message_recipients SET wake_attempt_count=1")
    deferral.restore_deferred_wake_budget(
        conn, message_id="pending", session_id="own", now=NOW
    )
    stored = conn.execute(
        "SELECT wake_attempt_count,wake_after FROM session_message_recipients"
    ).fetchone()
    assert stored[0] == 0
    assert stored[1] == NOW + timedelta(
        seconds=recipient_policy(conn, row).wake_after_idle_seconds
    )


def test_wake_rows_keep_org_owner_and_actor(world, monkeypatch):
    conn, owner, _ = world
    row = receipt(conn)
    monkeypatch.setattr(wake, "_native_wake_route_available", lambda *a, **kw: True)
    eligible = wake.wake_eligible_recipients(conn, now=NOW)
    assert len(eligible) == 1
    assert (
        eligible[0]["project_id"],
        eligible[0]["org_id"],
        eligible[0]["actor_id"],
    ) == (None, row["org_id"], owner)


def test_poll_upkeep_threads_relay_actor(monkeypatch):
    seen = []

    def capture(*args, **kwargs):
        seen.append(kwargs)
        return []

    for name in (
        "session_stale_alive_probe.probe_stale_alive_sessions",
        "session_native_turn_end.probe_targets",
        "session_vendor_error_resume.resume_vendor_error_sessions",
    ):
        monkeypatch.setattr("yoke_core.domain." + name, capture)
    upkeep.sweep_quiet_claim_holders(None, machine_id=MACHINE, projects=[], actor_id=41)
    upkeep.stuck_native_turn_probes(None, machine_id=MACHINE, projects=[], actor_id=41)
    upkeep.resume_vendor_error_sessions(
        None, machine_id=MACHINE, projects=[], actor_id=41
    )
    assert [kw.get("relay_actor_id", kw.get("actor_id")) for kw in seen] == [41, 41, 41]
    assert all(kw["authorized_projects"] == [] for kw in seen)


@pytest.mark.parametrize("kind", ["poll", "turn_end", "liveness", "idle_hosts"])
def test_poll_and_report_handlers_thread_relay_actor(world, monkeypatch, kind):
    conn, _, _ = world
    seen = []
    monkeypatch.setattr(db_helpers, "connect", lambda: NoCloseConnection(conn))
    monkeypatch.setattr(relay, "_require_active_machine", lambda *a, **kw: None)
    monkeypatch.setattr(
        "yoke_core.domain.handlers.session_relay_idle_hosts._require_active_machine",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.session_relay_authorization.require_relay_project_authority",
        lambda *a, **kw: None,
    )

    def capture(*args, **kwargs):
        seen.append(kwargs)
        return {}

    payload = {"relay_id": "r", "machine_id": MACHINE, "projects": []}
    if kind == "poll":
        for name in (
            "sweep_quiet_claim_holders",
            "resume_vendor_error_sessions",
            "stuck_native_turn_probes",
        ):
            monkeypatch.setattr(relay, name, capture)
        monkeypatch.setattr(
            "yoke_core.domain.session_relay.claim_relay_job",
            lambda *a, **kw: SimpleNamespace(to_dict=lambda: {}),
        )
        payload = dict(claim_payload(), projects=[])
        outcome = relay.handle_relay_claim(
            relay_request("session_control.relay.claim", payload)
        )
        assert [kw["actor_id"] for kw in seen] == [41, 41, 41]
    else:
        module, name = {
            "turn_end": ("session_native_turn_end", "apply_native_turn_ends"),
            "liveness": (
                "session_process_liveness_report",
                "apply_verified_process_death_reports",
            ),
            "idle_hosts": ("session_idle_host_report", "apply_idle_host_report"),
        }[kind]
        handler = (
            handle_relay_idle_hosts
            if kind == "idle_hosts"
            else getattr(relay, "handle_relay_" + kind)
        )
        monkeypatch.setattr("yoke_core.domain." + module + "." + name, capture)
        monkeypatch.setattr(
            "yoke_core.domain.session_launch_unregistered_death.apply_unregistered_native_death_reports",
            lambda *a, **kw: {},
        )
        outcome = handler(relay_request("session_control.relay." + kind, payload))
        assert seen[0]["relay_actor_id"] == 41
    assert outcome.primary_success


@pytest.mark.parametrize(
    "surface", ["claude-desktop", "codex-desktop", "cursor-desktop"]
)
def test_operator_notice_org_no_hidden_project(world, surface):
    conn, owner, _ = world
    row = dict(
        receipt(conn), executor_surface=surface, state="pending", message_created_at=OLD
    )
    notice = operator.notify_operator_to_wake(conn, row, now=NOW)
    assert notice is not None
    stored = conn.execute(
        "SELECT body,sender_actor_id FROM session_messages WHERE message_id=%s",
        (notice,),
    ).fetchone()
    assert "project" not in stored[0] and "org's message expiry" in stored[0]
    assert stored[1] is None
    assert (
        conn.execute(
            "SELECT actor_id FROM actor_message_recipients WHERE message_id=%s",
            (notice,),
        ).fetchone()[0]
        == owner
    )


@pytest.mark.parametrize(
    "engine,sender_session",
    [(False, "project"), (True, None), (True, "project"), (True, "own")],
)
def test_failure_notice_org_owner(world, monkeypatch, engine, sender_session):
    conn, owner, sender = world
    row = receipt(conn)
    conn.execute(
        "UPDATE session_messages SET sender_actor_id=%s,sender_session_id=%s",
        (None if engine else sender, sender_session),
    )
    conn.execute(
        "INSERT INTO session_message_attempts(attempt_id,message_id,target_session_id,attempt_kind,started_at,completed_at,result_code) VALUES ('failed','pending','own','wake_relay',%s,%s,'failed')",
        (OLD, NOW),
    )
    monkeypatch.setattr(
        failure,
        "resolve_steering_address",
        lambda *a, **kw: pytest.fail("org notice used project steering"),
    )
    notice = failure.notify_failed_wake(conn, row, now=NOW, max_attempts=3)
    assert notice is not None
    actors = conn.execute(
        "SELECT actor_id FROM actor_message_recipients WHERE message_id=%s", (notice,)
    ).fetchall()
    assert [r[0] for r in actors] == [owner if engine else sender]
    sessions = conn.execute(
        "SELECT session_id FROM session_message_recipients WHERE message_id=%s",
        (notice,),
    ).fetchall()
    assert [r[0] for r in sessions] == ([] if engine else ["project"])
    snapshot = conn.execute(
        "SELECT selector_snapshot FROM session_messages WHERE message_id=%s", (notice,)
    ).fetchone()[0]
    assert "steering" not in snapshot
