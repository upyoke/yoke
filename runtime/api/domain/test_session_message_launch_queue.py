"""Mail sent between staffing an item and the worker claiming it."""

import json
from datetime import timedelta

import pytest

from yoke_core.domain.session_message_delivery import (
    lease_for_hook,
    complete_hook_lease,
)
from yoke_core.domain.session_message_service import send_message, preview_message
from yoke_core.domain.session_message_store import message_details, cancel_message_rows
from yoke_core.domain.session_message_page import read_message_page
from yoke_core.domain.session_message_types import SessionMessageError
from runtime.api.domain.test_session_message_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
    pin_message_clocks,
)
from runtime.api.domain.test_session_launch_assignment_postgres import (
    admission as admission,
    _session,
    _launch,
    _claim,
)


def world(monkeypatch, *, surface="codex-cli"):
    pin_message_clocks(monkeypatch)
    from yoke_core.domain import session_message_launch_queue

    monkeypatch.setattr(session_message_launch_queue, "utc_now", lambda: NOW)
    conn = message_connection()
    conn.execute("DELETE FROM work_claims WHERE target_kind='item'")
    conn.execute(
        "UPDATE harness_sessions SET executor_surface=? WHERE session_id='s4'",
        (surface,),
    )
    # Launch instruction storage and its queue are the same records as real launches.
    conn.execute(
        "INSERT INTO session_messages(message_id,sender_actor_id,body,body_sha256,"
        "selector_snapshot,created_at,expires_at) VALUES ('mandate',10,'Claim item',"
        "'digest','{}',?,?)",
        (NOW_TEXT, (NOW + timedelta(hours=1)).isoformat()),
    )
    conn.execute(
        "INSERT INTO session_launches(launch_id,requester_actor_id,project_id,"
        "requested_surface,selected_surface,session_name,allow_surface_fallback,"
        "message_id,state,deadline_at,created_at,origin) VALUES "
        "('launch',10,1,?,?,'ALP-1: Test work',0,'mandate','assigned',?,?,'steering')",
        (surface, surface, (NOW + timedelta(minutes=10)).isoformat(), NOW_TEXT),
    )
    conn.commit()
    return conn


def send(conn, **kwargs):
    return send_message(
        conn,
        actor_id=10,
        sender_session_id=None,
        selector=selector(public_refs=["ALP-1"]),
        body="Include the scope amendment.",
        now=NOW,
        **kwargs,
    )


def claim(conn, *, session="s4", item=101):
    conn.execute(
        "INSERT INTO work_claims(session_id,target_kind,scope,claimed_at) "
        "VALUES (?,'item',?,?)",
        (session, json.dumps({"item_id": item}), NOW_TEXT),
    )
    conn.commit()


def register(conn):
    conn.execute(
        "UPDATE session_launches SET registered_session_id='s4',"
        "state='awaiting_registration' WHERE launch_id='launch'"
    )
    conn.commit()


@pytest.mark.parametrize(
    "surface", ["codex-cli", "claude-cli", "cursor-cli", "codex-desktop"]
)
def test_queued_before_registration_delivers_only_after_own_claim(monkeypatch, surface):
    conn = world(monkeypatch, surface=surface)
    # The manifest owns each harness's actual event spelling.
    from yoke_contracts.session_control.capabilities import capability_for_surface

    event = capability_for_surface(surface).inject_events[-1]
    preview = preview_message(
        conn, actor_id=10, selector=selector(public_refs=["ALP-1"]), now=NOW
    )
    assert preview["recipient_count"] == 1
    sent = send(conn, supplied_confirmation_token=preview["confirmation_token"])
    assert (
        message_details(conn, sent["message_id"])["selector_snapshot"]["launch_id"]
        == "launch"
    )
    assert sent["recipient_count"] == 1
    register(conn)
    assert lease_for_hook(conn, session_id="s4", hook_event=event, limit=10) is None
    claim(conn, item=201)
    assert lease_for_hook(conn, session_id="s4", hook_event=event, limit=10) is None
    claim(conn)
    lease = lease_for_hook(conn, session_id="s4", hook_event=event, limit=10)
    assert [row["message_id"] for row in lease["messages"]] == [sent["message_id"]]
    complete_hook_lease(
        conn, lease_id=lease["lease_id"], injected=True, result="injected"
    )
    assert lease_for_hook(conn, session_id="s4", hook_event=event, limit=10) is None
    assert (
        message_details(conn, sent["message_id"])["recipients"][0]["state"]
        == "injected"
    )


def test_pending_mail_is_listed_with_launch_and_disappears_from_other_sessions(
    monkeypatch,
):
    conn = world(monkeypatch)
    sent = send(conn, idempotency_key="amendment")
    assert send(conn, idempotency_key="amendment")["deduplicated"]
    page = read_message_page(
        conn, actor_id=10, caller_session_id=None, state="pending", projects=[1]
    )
    row = next(
        row for row in page["messages"] if row["message_id"] == sent["message_id"]
    )
    assert row["recipient_count"] == 1
    assert row["recipient_states"] == ["pending"]
    assert page["actionable_count"] == 1
    page = read_message_page(conn, actor_id=10, caller_session_id="s1", session_id="s1")
    assert sent["message_id"] not in {row["message_id"] for row in page["messages"]}


def test_no_launch_keeps_original_refusal_and_a_holder_wins(monkeypatch):
    conn = world(monkeypatch)
    conn.execute("DELETE FROM session_launches")
    conn.commit()
    with pytest.raises(SessionMessageError) as refused:
        send(conn)
    assert refused.value.code == "zero_recipients"
    assert "so it addresses nobody" in str(refused.value)
    claim(conn)
    assert send(conn)["recipients"][0]["session_id"] == "s4"


@pytest.mark.parametrize("state", ["cancelled", "failed", "expired", "outcome_unknown"])
def test_failed_launch_is_named_and_queued_mail_never_moves_to_replacement(
    monkeypatch, state
):
    conn = world(monkeypatch)
    sent = send(conn)
    conn.execute(
        "UPDATE session_launches SET state=? WHERE launch_id='launch'", (state,)
    )
    conn.commit()
    with pytest.raises(SessionMessageError, match="launch"):
        send(conn)
    conn.execute("UPDATE session_launches SET registered_session_id='s4'")
    conn.commit()
    claim(conn)
    assert (
        lease_for_hook(conn, session_id="s4", hook_event="PostToolUse", limit=10)
        is None
    )
    conn.execute("DELETE FROM work_claims WHERE target_kind='item'")
    claim(conn, session="s1")
    # A replacement claimant cannot steal mail from the failed launch.
    from yoke_core.domain.session_message_launch_queue import bind_item_launch_mail

    bind_item_launch_mail(conn, session_id="s1", now=NOW)
    assert not message_details(conn, sent["message_id"])["recipients"]


@pytest.mark.parametrize("cancel", [True, False])
def test_cancelled_or_expired_message_never_binds(monkeypatch, cancel):
    conn = world(monkeypatch)
    sent = send(conn)
    if cancel:
        cancel_message_rows(
            conn,
            message_id=sent["message_id"],
            actor_id=10,
            reason="obsolete",
            cancelled_at=NOW,
        )
    else:
        conn.execute(
            "UPDATE session_messages SET expires_at=? WHERE message_id=?",
            (NOW_TEXT, sent["message_id"]),
        )
    conn.commit()
    register(conn)
    claim(conn)
    assert (
        lease_for_hook(conn, session_id="s4", hook_event="PostToolUse", limit=10)
        is None
    )
    assert not message_details(conn, sent["message_id"])["recipients"]


def test_queue_requires_sender_permission(monkeypatch):
    conn = world(monkeypatch)
    with pytest.raises(SessionMessageError) as refused:
        send_message(
            conn,
            actor_id=11,
            sender_session_id=None,
            selector=selector(public_refs=["ALP-1"]),
            body="A scope change.",
            now=NOW,
        )
    assert refused.value.code == "unauthorized_target"


def test_idempotent_retry_after_claim_preserves_original_message(monkeypatch):
    conn = world(monkeypatch)
    sent = send(conn, idempotency_key="scope")
    register(conn)
    claim(conn)
    duplicate = send(conn, idempotency_key="scope")
    assert duplicate["deduplicated"]
    assert duplicate["message_id"] == sent["message_id"]


def test_cli_receipt_preview_and_read_name_queued_launch(monkeypatch):
    from io import StringIO
    from yoke_cli.commands.adapters.session_control_human_output import (
        write_message_result,
    )

    conn = world(monkeypatch)
    preview = preview_message(
        conn, actor_id=10, selector=selector(public_refs=["ALP-1"]), now=NOW
    )
    output = StringIO()
    write_message_result(preview, output)
    assert "worker's claim" in output.getvalue()
    sent = send(conn)
    output = StringIO()
    write_message_result(sent, output)
    assert "queued for 1 recipient" in output.getvalue()
    output = StringIO()
    write_message_result(
        {"message": message_details(conn, sent["message_id"])}, output, with_body=True
    )
    assert "awaiting_work_claim" in output.getvalue()


def test_postgres_queue_read_and_claim_binding(admission, monkeypatch):
    from yoke_contracts.timestamps import parse_instant
    from yoke_core.domain import actor_permissions, session_message_delivery
    from yoke_core.domain import session_message_page, session_message_launch_queue
    from yoke_core.domain.project_identity import render_item_ref

    conn, item, actor = admission
    at = parse_instant("2026-10-08T12:00:00Z")
    for module in (
        session_message_delivery,
        session_message_page,
        session_message_launch_queue,
    ):
        monkeypatch.setattr(module, "utc_now", lambda: at)
    actor_permissions.grant_actor_project_role(
        conn, actor_id=actor, project_id=item["project_id"], role_name="operator"
    )
    _session(admission, "worker")
    conn.execute(
        "UPDATE harness_sessions SET actor_id=%s,executor_surface='codex-cli',"
        "executor_version='0.161.0' WHERE session_id='worker'",
        (actor,),
    )
    _launch(admission, "pending-launch", state="assigned")
    conn.execute(
        "UPDATE session_launches SET origin='steering',deadline_at=%s",
        (at + timedelta(minutes=10),),
    )
    conn.commit()
    ref = render_item_ref(conn, item["id"], required=True)
    sent = send_message(
        conn,
        actor_id=actor,
        sender_session_id=None,
        selector=selector(public_refs=[ref]),
        body="Include the scope amendment.",
        now=at,
    )
    page = read_message_page(
        conn,
        actor_id=actor,
        caller_session_id=None,
        state="pending",
        projects=[item["project_id"]],
    )
    assert sent["message_id"] in {row["message_id"] for row in page["messages"]}
    conn.execute(
        "UPDATE session_launches SET registered_session_id='worker',"
        "state='awaiting_registration'"
    )
    _claim(admission, "worker", released=False)
    conn.commit()
    lease = lease_for_hook(
        conn, session_id="worker", hook_event="PostToolUse", limit=10
    )
    assert sent["message_id"] in {row["message_id"] for row in lease["messages"]}


def test_claim_arriving_during_send_resolves_to_new_holder(monkeypatch):
    from yoke_core.domain import session_message_service

    conn = world(monkeypatch)
    real_resolve = session_message_service.resolve_recipients

    def claim_during_resolution(*args, **kwargs):
        claim(conn)
        return []

    monkeypatch.setattr(
        session_message_service, "resolve_recipients", claim_during_resolution
    )
    sent = send(conn)
    assert sent["recipients"][0]["session_id"] == "s4"
    monkeypatch.setattr(session_message_service, "resolve_recipients", real_resolve)
