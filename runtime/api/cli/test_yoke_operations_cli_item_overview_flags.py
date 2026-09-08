"""``yoke items overview list`` flags stay at parity with the read contract."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from yoke_cli.main import main as cli_main
from yoke_core.domain.handlers.item_page_reads import (
    ItemsOverviewListRequest,
    handle_items_overview_list,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


def _run(*argv: str) -> tuple[int, FunctionCallRequest]:
    captured: list[FunctionCallRequest] = []

    def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        captured.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            request_id=request.request_id,
            version=request.version,
            result={},
        )

    with (
        patch.dict("os.environ", {"YOKE_SESSION_ID": "item-overview-flags-test"}),
        patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=dispatch,
        ),
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        redirect_stdout(io.StringIO()),
        redirect_stderr(io.StringIO()),
    ):
        result = cli_main(list(argv))
    assert captured
    return result, captured[-1]


def test_overview_list_forwards_the_website_overview_read_and_next_page() -> None:
    result, overview = _run(
        "items", "overview", "list",
        "--project", "yoke",
        "--relevance", "overview",
    )
    assert result == 0
    assert overview.function == "items.overview.list"
    assert overview.target.kind == "global"
    assert overview.payload == {"project": "yoke", "relevance": "overview"}

    result, first_page = _run(
        "items", "overview", "list",
        "--projects", "yoke, platform",
        "--search", "roster",
        "--workflow", "dash",
        "--status", "implementing",
        "--page-size", "50",
    )
    assert result == 0
    assert first_page.payload == {
        "projects": ["yoke", "platform"],
        "search": "roster",
        "workflow": "dash",
        "status": "implementing",
        "page_size": 50,
    }

    result, second_page = _run(
        "items", "overview", "list",
        "--page-size", "50",
        "--cursor", "opaque-next-cursor",
    )
    assert result == 0
    assert second_page.payload == {
        "page_size": 50,
        "cursor": "opaque-next-cursor",
    }


def test_overview_list_flags_cover_every_request_field() -> None:
    result, every_field = _run(
        "items", "overview", "list",
        "--project", "yoke",
        "--projects", "yoke",
        "--limit", "25",
        "--relevance", "overview",
        "--search", "roster",
        "--workflow", "dash",
        "--status", "implementing",
        "--page-size", "50",
        "--cursor", "opaque-next-cursor",
    )
    assert result == 0
    assert set(every_field.payload) == set(ItemsOverviewListRequest.model_fields)


def test_overview_list_omits_every_option_the_operator_did_not_name() -> None:
    result, bare = _run("items", "overview", "list")
    assert result == 0
    assert bare.payload == {}

    result, unpaged = _run(
        "items", "overview", "list", "--project", "yoke", "--limit", "25",
    )
    assert result == 0
    assert unpaged.payload == {"project": "yoke", "limit": 25}


def test_overview_list_leaves_invalid_combinations_to_the_request_model() -> None:
    """The CLI forwards; the read owns the named refusal and its recovery."""
    result, forwarded = _run(
        "items", "overview", "list",
        "--relevance", "overview",
        "--page-size", "50",
    )
    assert result == 0
    assert forwarded.payload == {"relevance": "overview", "page_size": 50}

    outcome = handle_items_overview_list(forwarded)
    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.jsonpath == "$.payload.relevance"


def test_overview_list_out_of_range_page_size_is_refused_by_the_read() -> None:
    result, forwarded = _run(
        "items", "overview", "list", "--page-size", "10000",
    )
    assert result == 0
    assert forwarded.payload == {"page_size": 10000}

    outcome = handle_items_overview_list(forwarded)
    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"
