"""Messages keep direct addresses precise and broadcasts free of sender echoes."""

import pytest

from yoke_core.domain.actor_permissions import ROLE_ADMIN, grant_actor_org_role
from yoke_core.domain.session_message_service import preview_message, send_message
from yoke_core.domain.session_message_selectors import resolve_recipients
from yoke_core.domain.session_message_types import SessionMessageError
from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    pin_message_clocks,
    selector,
)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    pin_message_clocks(monkeypatch)


def message(conn, target, *, send=False):
    kwargs = dict(actor_id=10, sender_session_id="s1", selector=target, now=NOW)
    token = None
    if target.universe:
        grant_actor_org_role(conn, actor_id=10, org_id=1, role_name=ROLE_ADMIN)
        token = preview_message(conn, **kwargs)["confirmation_token"]
    if send:
        return send_message(
            conn, body="Inspect this work.", supplied_confirmation_token=token, **kwargs
        )
    return preview_message(conn, **kwargs)


@pytest.mark.parametrize("send", [False, True])
@pytest.mark.parametrize(
    "anchor",
    [
        {"public_refs": ["ALP-1"]},
        {"epic_tasks": ["ALP-1:1"]},
        {"process_keys": ["release"]},
        {"session_ids": ["s2"]},
    ],
)
def test_project_cannot_widen_direct_message(anchor, send):
    conn = message_connection()
    with pytest.raises(SessionMessageError) as raised:
        message(conn, selector(projects=["alpha"], **anchor), send=send)
    assert raised.value.code == "selector_invalid"
    assert "drop --project; the item ref already names its project" in str(raised.value)
    assert conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0] == 0


@pytest.mark.parametrize("send", [False, True])
@pytest.mark.parametrize(
    "target",
    [
        selector(public_refs=["ALP-1"]),
        selector(session_ids=["s1"]),
        selector(universe=True, session_ids=["s1"]),
    ],
)
def test_explicit_sender_address_still_delivers(target, send):
    conn = message_connection()
    result = message(conn, target, send=send)
    assert "s1" in [row["session_id"] for row in result["recipients"]]
    if target.public_refs or not target.universe:
        assert [row["session_id"] for row in result["recipients"]] == ["s1"]


@pytest.mark.parametrize("send", [False, True])
@pytest.mark.parametrize(
    "target", [selector(projects=["alpha"]), selector(universe=True)]
)
def test_bulk_message_excludes_sender(target, send):
    conn = message_connection()
    result = message(conn, target, send=send)
    ids = [row["session_id"] for row in result["recipients"]]
    assert "s1" not in ids
    assert "s2" in ids
    if send:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM session_message_recipients "
                "WHERE message_id=? AND session_id='s1'",
                (result["message_id"],),
            ).fetchone()[0]
            == 0
        )


def test_shared_wake_resolution_preserves_project_union_and_sender():
    conn = message_connection()
    recipients = resolve_recipients(
        conn,
        selector(projects=["alpha"], public_refs=["ALP-1"]),
        actor_id=10,
        now=NOW,
    )
    assert {row.session_id for row in recipients} == {"s1", "s2"}
