"""Shipped Pack payloads retain their non-import contract tests when bounded."""

import pytest

from yoke_core.tools.impacted_tests import build_import_index, select


@pytest.mark.parametrize(
    "prefix",
    [
        "packs/structured-events/",
        "packages/yoke-core/src/yoke_core/install_bundle_tree/packs/structured-events/",
    ],
)
@pytest.mark.parametrize(
    "payload", ["pack.json", "versions/2.0.0/files/events/events.ts"]
)
def test_pack_payload_selects_catalog_and_installed_contracts(
    tmp_path, prefix, payload
):
    source = prefix + payload
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
