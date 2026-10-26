"""All event read shapes apply the same permission predicate before selecting."""

import pytest
from runtime.api.auth_test_helpers import mint_api_auth_context
from runtime.api.conftest import insert_event
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import events_reads

READS = ["query", "count", "anomalies", "tail"]


def request(verb, actor, payload):
    return FunctionCallRequest(
        function=f"events.{verb}.run",
        actor=ActorContext(actor_id=str(actor), session_id="caller"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


@pytest.mark.parametrize("verb", READS)
def test_org_admin_reads_unattributed_but_project_owner_does_not(test_db, verb):
    auth = mint_api_auth_context(test_db)
    insert_event(
        test_db, event_id="global", session_id="projectless", anomaly_flags="flag"
    )
    test_db.execute("UPDATE events SET project_id=NULL WHERE event_id='global'")
    test_db.commit()
    handler = getattr(events_reads, f"handle_events_{verb}")
    result = handler(request(verb, auth.actor_id, {}))
    assert result.primary_success
    assert (
        result.result_payload["count"]
        if verb == "count"
        else len(result.result_payload["rows"])
    ) == 1
    # An explicit project excludes project-less events, including for admins.
    result = handler(request(verb, auth.actor_id, {"project": "yoke"}))
    assert result.primary_success
    assert (
        result.result_payload["count"]
        if verb == "count"
        else len(result.result_payload["rows"])
    ) == 0
    test_db.execute(
        "INSERT INTO projects (id, slug, name, org_id, created_at, public_item_prefix) VALUES (9999, 'other', 'Other', %s, NOW(), 'OTH')",
        (auth.org_id,),
    )
    insert_event(test_db, event_id="hidden", project_id=9999, anomaly_flags="flag")
    test_db.execute("DELETE FROM actor_org_roles WHERE actor_id=%s", (auth.actor_id,))
    test_db.commit()
    result = handler(request(verb, auth.actor_id, {}))
    assert result.primary_success
    assert (
        result.result_payload["count"]
        if verb == "count"
        else len(result.result_payload["rows"])
    ) == 0
    denied = handler(request(verb, auth.actor_id, {"project": "other"}))
    assert not denied.primary_success
    assert denied.error.code == "events_scope_denied"


@pytest.mark.parametrize("history", [False, True])
def test_projectless_session_query_is_visible_to_admin(test_db, history):
    auth = mint_api_auth_context(test_db)
    insert_event(test_db, event_id="session-global", session_id="projectless")
    test_db.execute("UPDATE events SET project_id=NULL WHERE event_id='session-global'")
    test_db.commit()
    payload = {"session_id": "projectless"}
    if history:
        payload["history"] = {"limit": 10}
    result = events_reads.handle_events_query(request("query", auth.actor_id, payload))
    assert result.primary_success
    assert len(result.result_payload["rows"]) == 1
