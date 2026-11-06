"""Roster handlers page complete rows and retain surrounding facts."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from runtime.api.domain.test_list_paging_reads import request
from yoke_core.domain.handlers import (
    capabilities_list,
    strategy_doc_surface_reads as surfaces,
)


def test_capability_roster_pages_all_projects_and_preserves_fields():
    rows = [
        {"project_slug": str(n), "settings": {"lines": "first\nsecond"}}
        for n in range(61)
    ]
    seen = []
    with patch(
        "yoke_core.domain.capabilities_list_read.list_capabilities", return_value=rows
    ):
        for offset in (0, 25, 50):
            result = capabilities_list.handle_capabilities_list(
                request(
                    "projects.capabilities.list",
                    {"kind": "global"},
                    {"limit": 25, "offset": offset},
                )
            ).result_payload
            seen.extend(result["rows"])
            assert result["fields"]
            assert result["next_offset"] == (offset + 25 if offset < 50 else None)
    assert seen == rows


def test_surface_roster_pages_documents_and_retains_activity():
    rows = [{"slug": str(n), "recent_writes": n} for n in range(61)]
    writes = [{"day": "2026-01-01", "writes": 4}]
    conn = MagicMock()
    seen = []
    with (
        patch("yoke_core.domain.db_helpers.connect", return_value=nullcontext(conn)),
        patch.object(
            surfaces,
            "_project",
            return_value=(SimpleNamespace(id=2, slug="example"), None),
        ),
        patch.object(surfaces, "list_strategy_surfaces", return_value=rows),
        patch.object(surfaces, "strategy_write_activity", return_value=writes),
    ):
        for offset in (0, 25, 50):
            result = surfaces.handle_surface_list(
                request(
                    "strategy.surface.list",
                    {"kind": "global", "project_id": "2"},
                    {"limit": 25, "offset": offset},
                )
            ).result_payload
            seen.extend(result["docs"])
            assert result["writes"] == writes
            assert result["project_slug"] == "example"
            assert result["next_offset"] == (offset + 25 if offset < 50 else None)
    assert seen == rows
