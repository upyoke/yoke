"""Structural tests for the reference ``api-route.ts`` template.

Companion to ``test_events_ts.py`` (which covers the ``events.ts``
client-side template). Confirms required handlers, validation rules,
response shapes, and the storage-options documentation block on the
TypeScript API route stub.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_API_ROUTE = _HERE / "api-route.ts"


@pytest.fixture(scope="module")
def api_route() -> str:
    assert _API_ROUTE.is_file(), f"reference template missing: {_API_ROUTE}"
    return _API_ROUTE.read_text()


def _must_contain(blob: str, needle: str, label: str) -> None:
    assert needle in blob, f"{label}: pattern not found ({needle!r})"


class TestApiRouteHandlers:
    @pytest.mark.parametrize("needle,label", [
        ("export async function POST", "POST handler exported"),
        ("export async function GET", "GET handler exported"),
        ("NextRequest", "NextRequest import"),
        ("NextResponse", "NextResponse import"),
    ])
    def test_handler_surface(self, api_route: str, needle: str, label: str) -> None:
        _must_contain(api_route, needle, label)


class TestApiRouteValidation:
    def test_validates_content_type(self, api_route: str) -> None:
        _must_contain(api_route, "application/json", "validates Content-Type")

    def test_validates_events_array(self, api_route: str) -> None:
        # The original shell test used ``events.*array`` as a grep regex; we
        # assert both tokens literally since the TS source contains an
        # ``Array.isArray(events)`` guard on the request body.
        assert "events" in api_route
        assert "array" in api_route.lower()

    @pytest.mark.parametrize("needle,label", [
        ("MAX_BATCH_SIZE", "validates batch size limit"),
        ("MAX_BATCH_SIZE = 50", "max batch size is 50"),
        ("REQUIRED_FIELDS", "validates required fields"),
        ("event_id", "validates event_id"),
        ("event_name", "validates event_name"),
        ("event_kind", "validates event_kind"),
        ("event_type", "validates event_type"),
        ("event_time", "validates event_time"),
        ("VALID_KINDS", "validates event kind enum"),
        ("MAX_REQUEST_BYTES = 524288", "request size limit 512KB"),
        ("Events array must not be empty", "empty array rejected"),
    ])
    def test_validation_rules(self, api_route: str, needle: str, label: str) -> None:
        _must_contain(api_route, needle, label)


class TestApiRouteResponse:
    @pytest.mark.parametrize("needle,label", [
        ("accepted: events.length", "success returns accepted count"),
        ("error:", "error returns error message"),
        ("405", "405 for non-POST"),
        ("400", "400 for validation errors"),
        ("413", "413 for oversized request"),
    ])
    def test_response_format(self, api_route: str, needle: str, label: str) -> None:
        _must_contain(api_route, needle, label)


class TestApiRouteStorageOptionsDocumented:
    @pytest.mark.parametrize("needle,label", [
        ("Option A", "Option A: database"),
        ("Option B", "Option B: proxy"),
        ("Option C", "Option C: log file"),
    ])
    def test_option_labels(self, api_route: str, needle: str, label: str) -> None:
        _must_contain(api_route, needle, label)
