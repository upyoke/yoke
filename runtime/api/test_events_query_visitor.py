"""Visitor filters preserve frontend and organization authorization boundaries."""

import json

import pytest

from runtime.api.auth_test_helpers import mint_api_auth_context
from runtime.api.conftest import insert_event
from runtime.api.domain.handlers.test_events_read_authorization import request
from yoke_core.domain.handlers import events_reads


@pytest.mark.parametrize("verb", ["query", "count", "anomalies"])
def test_visitor_reads_only_matching_frontend_rows_for_org_admin(test_db, verb):
    auth = mint_api_auth_context(test_db)
    for name, visitor, source in [
        ("match", "visitor-a", "frontend"),
        ("other", "visitor-b", "frontend"),
        ("backend", "visitor-a", "backend"),
    ]:
        insert_event(test_db, event_id=name, anomaly_flags="flag")
        test_db.execute(
            "UPDATE events SET project_id=NULL, source_type=%s, envelope=%s "
            "WHERE event_id=%s",
            (source, json.dumps({"visitor_id": visitor}), name),
        )
    test_db.commit()
    handler = getattr(events_reads, f"handle_events_{verb}")
    outcome = handler(request(verb, auth.actor_id, {"visitor_id": "visitor-a"}))
    assert outcome.primary_success
    if verb == "count":
        assert outcome.result_payload["count"] == 1
    else:
        assert [row["event_id"] for row in outcome.result_payload["rows"]] == ["match"]
    test_db.execute("DELETE FROM actor_org_roles WHERE actor_id=%s", (auth.actor_id,))
    test_db.commit()
    outcome = handler(request(verb, auth.actor_id, {"visitor_id": "visitor-a"}))
    assert outcome.primary_success
    assert outcome.result_payload.get("count", len(outcome.result_payload.get("rows", []))) == 0


@pytest.mark.parametrize("verb", ["query", "count", "anomalies"])
@pytest.mark.parametrize("served", [False, True])
def test_cli_carries_visitor_filter_and_refuses_older_serving_builds(verb, served):
    from runtime.api.cli.test_yoke_operations_cli_dispatch import _run_capture
    from yoke_contracts.api.function_call import FunctionCallResponse

    def reply(request):
        assert request.payload["visitor_id"] == "visitor-a"
        result = {"count": 0} if verb == "count" else {"rows": []}
        if served:
            result["visitor_id"] = "visitor-a"
        return FunctionCallResponse(
            success=True, function=request.function, version=request.version,
            request_id=request.request_id, result=result,
        )

    rc, out, err = _run_capture(
        reply, "events", verb, "--visitor-id", "visitor-a", "--json"
    )
    assert (rc == 0) == served
    if not served:
        assert "events_visitor_filter_unavailable" in out + err
