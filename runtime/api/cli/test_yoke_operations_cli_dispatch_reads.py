"""Dispatch-path tests for the cross-family reader subcommands.

Sibling of :mod:`test_yoke_operations_cli_dispatch` (kept separate so
each test file stays under the line cap). Covers the reader ids: events
tail/count/anomalies + extended query filters, claims path list/get,
ouroboros entry list/get, items list/search, shepherd dependency-list.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.cli.test_yoke_operations_cli_dispatch import (
    _CAPTURED_REQUESTS,
    _run_capture,
    _run_with_dispatch,
    _stub_dispatch_ok,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


class TestEventsReadDispatch:
    def test_events_tail_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "events", "tail", "--limit", "20",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "events.tail.run"
        assert req.target.kind == "global"
        assert req.payload == {"limit": 20}

    def test_events_count_dispatches_with_filters(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "events", "count", "--since", "4 hours ago",
            "--event-name", "QARunCompleted",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "events.count.run"
        assert req.payload == {
            "since": "4 hours ago", "event_name": "QARunCompleted",
        }

    def test_events_anomalies_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "events", "anomalies",
            "--since", "24 hours ago",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "events.anomalies.run"
        assert req.payload == {"since": "24 hours ago", "limit": 200}

    def test_events_query_session_filter_distinct_from_caller(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "events", "query", "--session", "s-filter",
            "--current-episode",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "events.query.run"
        assert req.payload["session_id"] == "s-filter"
        assert req.payload["current_episode"] is True
        # Caller identity stays the ambient session, not the filter.
        assert req.actor.session_id == "test-session"

    def test_events_query_current_episode_requires_session(self) -> None:
        rc, _out, err = _run_capture(
            _stub_dispatch_ok, "events", "query", "--current-episode",
        )
        assert rc == 2
        assert "--session" in err
        assert not _CAPTURED_REQUESTS


class TestDbReadDispatch:
    def test_db_read_dispatches(self) -> None:
        sql = "SELECT id, title FROM items ORDER BY id LIMIT 1"

        rc = _run_with_dispatch(_stub_dispatch_ok, "db", "read", sql)

        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "db.read.run"
        assert req.target.kind == "global"
        assert req.payload == {"sql": sql}

    def test_db_read_default_output_is_result_json(self) -> None:
        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result={"columns": ["id"], "rows": [{"id": 1}]},
            )

        rc, out, err = _run_capture(stub, "db", "read", "SELECT 1 AS id")

        assert rc == 0
        assert err == ""
        assert json.loads(out) == {"columns": ["id"], "rows": [{"id": 1}]}

    def test_db_read_json_flag_emits_envelope(self) -> None:
        rc, out, err = _run_capture(
            _stub_dispatch_ok, "db", "read", "SELECT 1", "--json",
        )

        assert rc == 0
        assert err == ""
        response = json.loads(out)
        assert response["function"] == "db.read.run"
        assert response["success"] is True
        assert response["result"] == {"echo": True}


class TestClaimsPathReadDispatch:
    def test_claims_path_list_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "claims", "path", "list", "--item", "1819",
            "--state", "planned,active", "--state", "blocked",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "claims.path.list"
        assert req.target.kind == "item"
        assert req.target.item_ref == "1819"
        assert req.payload == {"states": ["planned", "active", "blocked"]}

    def test_claims_path_get_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "claims", "path", "get", "77",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "claims.path.get"
        assert req.target.kind == "path_claim"
        assert req.target.path_claim_id == 77

    def test_claims_path_get_rejects_non_integer(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "claims", "path", "get", "abc",
        )
        assert rc == 2
        assert not _CAPTURED_REQUESTS

class TestOuroborosEntryDispatch:
    def test_entry_list_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "ouroboros", "entry", "list", "--unreviewed",
            "--project", "yoke", "--limit", "3",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "ouroboros.entry.list"
        assert req.payload == {
            "unreviewed": True, "project": "yoke", "limit": 3,
        }

    def test_entry_get_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "ouroboros", "entry", "get", "13009",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "ouroboros.entry.get"
        assert req.payload == {"entry_id": 13009}


class TestOuroborosFieldNoteReadDispatch:
    def test_field_note_list_dispatches_with_field_note_filter(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "ouroboros", "field-note", "list", "--unreviewed",
            "--project", "yoke", "--limit", "40",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "ouroboros.field_note.list"
        assert req.payload == {
            "category_prefix": "field-note-",
            "unreviewed": True,
            "project": "yoke",
            "limit": 40,
        }

    def test_field_note_get_dispatches_with_field_note_filter(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "ouroboros", "field-note", "get", "13270",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "ouroboros.field_note.get"
        assert req.payload == {
            "entry_id": 13270,
            "category_prefix": "field-note-",
        }


class TestItemsListingDispatch:
    def test_items_list_dispatches_with_filters(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items", "list", "--status", "done",
            "--fields", "id,title,status", "--limit", "5",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "items.list.run"
        assert req.target.kind == "global"
        assert req.payload == {
            "status": "done",
            "fields": ["id", "title", "status"],
            "limit": 5,
        }

    def test_items_list_frozen_flag_parses_binary(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "items", "list", "--frozen", "1",
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload == {"frozen": True}

    def test_items_list_rejects_bad_binary(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "items", "list", "--frozen", "maybe",
        )
        assert rc == 2
        assert not _CAPTURED_REQUESTS

    def test_items_list_defaults_scope_to_checkout_project(
        self, monkeypatch
    ) -> None:
        # 13468: an operator in a project checkout must see that project's
        # items by default, not the global backlog. The adapter resolves
        # the cwd->project context and pins it as the default scope.
        monkeypatch.setattr(
            "yoke_cli.commands.adapters.listing.client_project_context",
            lambda explicit: "2" if not explicit else explicit,
        )
        rc = _run_with_dispatch(_stub_dispatch_ok, "items", "list", "--limit", "3")
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload == {"project": "2", "limit": 3}

    def test_items_list_project_all_is_global_escape(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "yoke_cli.commands.adapters.listing.client_project_context",
            lambda explicit: "2" if not explicit else explicit,
        )
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "items", "list", "--project", "all",
        )
        assert rc == 0
        assert "project" not in _CAPTURED_REQUESTS[-1].payload

    def test_items_list_no_checkout_mapping_stays_global(
        self, monkeypatch
    ) -> None:
        # No checkout->project mapping (resolver returns None) preserves the
        # prior global-list behavior.
        monkeypatch.setattr(
            "yoke_cli.commands.adapters.listing.client_project_context",
            lambda explicit: None,
        )
        rc = _run_with_dispatch(_stub_dispatch_ok, "items", "list")
        assert rc == 0
        assert "project" not in _CAPTURED_REQUESTS[-1].payload

    def test_items_search_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "items", "search", "dedup keywords",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "items.search.run"
        assert req.payload == {"keywords": "dedup keywords"}

    def test_items_search_defaults_scope_to_checkout_project(
        self, monkeypatch
    ) -> None:
        # 13468: search defaults to the checkout's project, mirroring list.
        monkeypatch.setattr(
            "yoke_cli.commands.adapters.listing.client_project_context",
            lambda explicit: "2" if not explicit else explicit,
        )
        rc = _run_with_dispatch(_stub_dispatch_ok, "items", "search", "wibble")
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload == {
            "keywords": "wibble", "project": "2",
        }

    def test_items_search_project_all_is_global_escape(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "yoke_cli.commands.adapters.listing.client_project_context",
            lambda explicit: "2" if not explicit else explicit,
        )
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "items", "search", "wibble", "--project", "all",
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload == {"keywords": "wibble"}


class TestShepherdDependencyListDispatch:
    def test_positional_item(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "shepherd", "dependency-list", "YOK-10",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "shepherd.dependency_list.run"
        assert req.target.kind == "item"
        assert req.target.item_ref == "YOK-10"

    def test_item_flag(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "shepherd", "dependency-list",
            "--item", "1819",
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].target.item_ref == "1819"

    def test_missing_item_is_usage_error(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok, "shepherd", "dependency-list",
        )
        assert rc == 2
        assert not _CAPTURED_REQUESTS
