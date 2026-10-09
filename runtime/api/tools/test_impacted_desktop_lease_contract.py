"""Desktop assistance selects its retained-lease liveness companions."""

from pathlib import Path

import pytest

from yoke_core.tools._impacted_contract_tests_session_control import (
    DESKTOP_LEASE_ACCESS_SOURCE_PATHS,
    DESKTOP_LEASE_ACCESS_TESTS,
)
from yoke_core.tools.impacted_tests import build_import_index, select


@pytest.mark.parametrize("source", sorted(DESKTOP_LEASE_ACCESS_SOURCE_PATHS))
def test_desktop_lease_companions_survive_bounded_document_deferral(
    tmp_path: Path, source: str
):
    doc = "docs/desktop-assistance.md"
    for relative in [source, doc, *DESKTOP_LEASE_ACCESS_TESTS]:
        file = tmp_path / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(
            "def test_contract(): pass\n"
            if file.name.startswith("test_")
            else "VALUE = 1\n"
        )

    selection = select([source, doc], build_import_index(tmp_path), bounded=True)

    assert selection.bounded_deferral
    assert set(DESKTOP_LEASE_ACCESS_TESTS) <= set(selection.files)
    assert f"desktop_lease_access_contract:{source}" in selection.widening_triggers
