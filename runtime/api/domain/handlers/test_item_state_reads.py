"""The CLI's item reads and the web Frontier carry one state projection."""

from runtime.api.fixtures.backlog import insert_item
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain.frontier_list_read import list_frontier
from yoke_core.domain.handlers.items_listing import handle_items_list
from yoke_core.domain.handlers.reads import handle_items_get


def test_item_state_agrees_across_reads(test_db):
    insert_item(test_db, id=841, project_sequence=81, workflow_id="issue",
                status="implementing", title="Consistent display",
                spec="Show the same pinned state on every item read.")
    test_db.commit()
    actor = ActorContext(actor_id=None, session_id="")
    fields = ["stage", "home_section", "next_actor", "progress"]
    get = handle_items_get(FunctionCallRequest(
        function="items.get.run", actor=actor,
        target=TargetRef(kind="item", item_id=841), payload={"fields": fields},
    ))
    listing = handle_items_list(FunctionCallRequest(
        function="items.list.run", actor=actor,
        target=TargetRef(kind="global"), payload={"fields": ["id", *fields]},
    ))
    assert get.primary_success and listing.primary_success
    listed = next(row for row in listing.result_payload["rows"] if row["id"].endswith("-81"))
    frontier = next(row for row in list_frontier()["ready_rows"] if row["item_id"].endswith("-81"))
    for key in fields:
        assert get.result_payload["fields"][key] == listed[key] == frontier[key]
    assert listed["home_section"] == "ready"
    assert listed["stage"]["id"] == "implementing"
    assert any(step["state"] == "active" for step in listed["progress"]["stages"])
