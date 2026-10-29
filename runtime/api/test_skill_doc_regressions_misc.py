"""Misc doc regressions: cross-tree links and retired events."""

from __future__ import annotations

import pytest

from runtime.api.skill_doc_regressions_test_helpers import REPO, _read


@pytest.mark.parametrize(
    ("document", "target"),
    (
        ("docs/qa-platform/cli-reference.md", ".yoke/docs/verification/platform.md"),
        (
            "docs/qa-platform/cli-reference.md",
            ".yoke/docs/functions/index.md",
        ),
    ),
)
def test_cross_tree_document_links_resolve(document: str, target: str) -> None:
    text = _read(REPO / document)
    assert target in text
    assert (REPO / target).is_file()


class TestRetiredEventNamesLeaveTheCatalog:
    """A name whose producer is gone has no catalog row, so boot deletes it."""

    @pytest.mark.parametrize(
        "name", ["WorktreeHandoffEmitted", "SessionExecutionScopeChanged"]
    )
    def test_retired_name_has_no_catalog_row(self, name):
        from yoke_core.domain.event_catalog import EVENT_CATALOG

        assert name not in EVENT_CATALOG
        assert f"| {name} |" not in _read(REPO / "docs" / "event-catalog.md")
