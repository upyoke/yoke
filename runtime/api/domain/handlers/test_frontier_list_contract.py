"""Frontier handler request contract, registration and browser admission."""

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.frontier_list_read import FRONTIER_READY_FIELDS
from yoke_core.domain.handlers.frontier_list import handle_frontier_list
from runtime.api.fixtures.backlog import insert_item


def _request(payload=None):
    return FunctionCallRequest(
        function="frontier.list",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


class TestHandler:
    def test_handler_returns_both_row_families(self, test_db):
        insert_item(
            test_db,
            id=81,
            title="handled",
            workflow_id="issue",
            status="implementing",
        )
        outcome = handle_frontier_list(_request())
        assert outcome.primary_success
        payload = outcome.result_payload
        assert payload["fields"]["ready"] == list(FRONTIER_READY_FIELDS)
        assert [row["item_id"] for row in payload["ready_rows"]] == ["YOK-81"]
        assert payload["blocked_rows"] == []

    def test_handler_unknown_project_is_typed_not_found(self, test_db):
        outcome = handle_frontier_list(_request({"project": "nope"}))
        assert not outcome.primary_success
        assert outcome.error.code == "not_found"
        assert "nope" in outcome.error.message

    def test_handler_bad_payload_types_are_typed_errors(self, test_db):
        for payload in ({"project": 7}, {"wip_cap": "five"}, {"wip_cap": True}):
            outcome = handle_frontier_list(_request(payload))
            assert not outcome.primary_success
            assert outcome.error.code == "payload_invalid"

    def test_handler_requires_global_target(self):
        outcome = handle_frontier_list(
            FunctionCallRequest(
                function="frontier.list",
                actor=ActorContext(actor_id=None, session_id=""),
                target=TargetRef(kind="item", item_id=1),
                payload={},
            ),
        )
        assert not outcome.primary_success
        assert outcome.error.code == "target_invalid"


class TestRegistrationAndAllowlist:
    def test_frontier_list_is_a_registered_claimless_read(self):
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain import yoke_function_registry as registry
        from yoke_core.domain.yoke_function_actor_identity import is_read_only

        registry.reset_registry_for_tests()
        try:
            register_all_handlers()
            entry = registry.lookup("frontier.list")
            assert entry is not None
            assert entry.target_kinds == ("global",)
            assert is_read_only(entry)
        finally:
            registry.reset_registry_for_tests()

    def test_browser_allowlist_contains_frontier_list(self):
        from yoke_core.ui.server import UI_READ_FUNCTION_ALLOWLIST

        assert "frontier.list" in UI_READ_FUNCTION_ALLOWLIST
