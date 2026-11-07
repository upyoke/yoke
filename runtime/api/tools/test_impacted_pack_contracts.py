"""Shipped Pack payloads retain their non-import contract tests when bounded."""

import pytest

from yoke_core.tools.impacted_tests import build_import_index, select


@pytest.mark.parametrize(
    "payload", ["pack.json", "versions/2.0.0/files/events/events.ts"]
)
def test_pack_payload_selects_catalog_and_installed_contracts(tmp_path, payload):
    source = "packs/structured-events/" + payload
    expected = {
        "runtime/api/domain/test_pack_catalog.py",
        "runtime/api/domain/test_pack_prerequisite_catalog.py",
        "runtime/api/domain/test_structured_events_pack.py",
    }
    for path, content in [
        (source, "{}"),
        *[(test, "def test_contract(): pass") for test in expected],
    ]:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    selection = select([source], build_import_index(tmp_path), bounded=True)
    assert expected <= set(selection.files)
    assert f"pack_catalog_contract:{source}" in selection.widening_triggers
    assert f"structured_events_pack_contract:{source}" in selection.widening_triggers


@pytest.mark.parametrize(
    "source",
    [
        "events/test_browser.mjs",
        "events/api-route.ts",
        "events/test_collector_instants.mjs",
    ],
)
def test_standalone_collector_selects_its_executable_contract(tmp_path, source):
    contract = "runtime/api/domain/test_structured_events_pack.py"
    for path, content in (
        (source, "export {};"),
        (contract, "def test_contract(): pass"),
    ):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    selection = select([source], build_import_index(tmp_path), bounded=True)
    assert contract in selection.files
    assert f"structured_events_pack_contract:{source}" in selection.widening_triggers
