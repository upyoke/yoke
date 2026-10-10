"""CLI dispatch contracts for item listing, search, and dependencies."""

from __future__ import annotations

import pytest

from runtime.api.cli.test_yoke_operations_cli_dispatch import (
    _CAPTURED_REQUESTS,
    _run_with_dispatch,
    _stub_dispatch_ok,
)


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


class TestItemsListingDispatch:
    def test_items_list_dispatches_with_filters(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items",
            "list",
            "--status",
            "done",
            "--fields",
            "id,title,status",
            "--limit",
            "5",
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
            _stub_dispatch_ok,
            "items",
            "list",
            "--frozen",
            "1",
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload == {"frozen": True}

    def test_items_list_rejects_bad_binary(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items",
            "list",
            "--frozen",
            "maybe",
        )
        assert rc == 2
        assert not _CAPTURED_REQUESTS

    def test_items_list_defaults_scope_to_checkout_project(self, monkeypatch) -> None:
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
            _stub_dispatch_ok,
            "items",
            "list",
            "--project",
            "all",
        )
        assert rc == 0
        assert "project" not in _CAPTURED_REQUESTS[-1].payload

    def test_items_list_no_checkout_mapping_stays_global(self, monkeypatch) -> None:
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
            _stub_dispatch_ok,
            "items",
            "search",
            "dedup keywords",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "items.search.run"
        assert req.payload == {"keywords": "dedup keywords"}

    def test_items_search_forwards_explicit_limit(self):
        assert (
            _run_with_dispatch(
                _stub_dispatch_ok, "items", "search", "wibble", "--limit", "60"
            )
            == 0
        )
        assert _CAPTURED_REQUESTS[-1].payload == {"keywords": "wibble", "limit": 60}

    def test_search_human_output_retains_status_and_more_count(self):
        import io
        from types import SimpleNamespace
        from yoke_cli.commands.adapters.listing import _write_search

        rows = [
            {
                "id": f"EX-{n}",
                "title": f"Match {n}",
                "status": "done" if n % 2 else "implementing",
            }
            for n in range(60, 40, -1)
        ]
        result = {"matches": rows, "total_count": 60}
        output = io.StringIO()
        _write_search(
            SimpleNamespace(success=True, result=result), output, io.StringIO()
        )
        assert len(output.getvalue()) <= 750
        assert len(output.getvalue().splitlines()) == 22
        assert "40 more; add --limit N" in output.getvalue()
        assert "EX-60\timplementing\tMatch 60" in output.getvalue()
        assert result["matches"] == rows
        import json
        from runtime.api.cli.test_yoke_operations_cli_dispatch import _run_capture

        def stub(request):
            response = _stub_dispatch_ok(request)
            response.result = result
            return response

        rc, stdout, stderr = _run_capture(stub, "items", "search", "match", "--json")
        assert rc == 0, stderr
        assert json.loads(stdout)["result"] == result

    def test_items_search_defaults_scope_to_checkout_project(self, monkeypatch) -> None:
        # 13468: search defaults to the checkout's project, mirroring list.
        monkeypatch.setattr(
            "yoke_cli.commands.adapters.listing.client_project_context",
            lambda explicit: "2" if not explicit else explicit,
        )
        rc = _run_with_dispatch(_stub_dispatch_ok, "items", "search", "wibble")
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload == {
            "keywords": "wibble",
            "project": "2",
        }

    def test_items_search_project_all_is_global_escape(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "yoke_cli.commands.adapters.listing.client_project_context",
            lambda explicit: "2" if not explicit else explicit,
        )
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items",
            "search",
            "wibble",
            "--project",
            "all",
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload == {"keywords": "wibble"}


class TestItemDependencyListDispatch:
    def test_positional_item(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items",
            "dependency",
            "list",
            "YOK-10",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "items.dependency.list"
        assert req.target.kind == "item"
        assert req.target.public_ref == "YOK-10"

    def test_item_flag(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items",
            "dependency",
            "list",
            "--item",
            "YOK-1819",
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].target.public_ref == "YOK-1819"

    def test_missing_item_is_usage_error(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "items",
            "dependency",
            "list",
        )
        assert rc == 2
        assert not _CAPTURED_REQUESTS
