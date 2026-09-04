"""Frozen raw-byte identities for migration entries carried by releases."""

from __future__ import annotations

import json

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_content_identity import raw_content_sha256
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_serving_version import (
    NEXT_RELEASE,
    declared_minimum,
)


MANIFEST_NAME = "released_history_digests.json"
VALIDATION_LEDGER_ENTRY = "0035_clear_unproven_onboard_activation_latch"
VALIDATION_LEDGER_DIGEST = (
    "1c6a854577ba890eb69882e58030c9af10f4ffcaa4969929fbd51941eb6e52ef"
)


def _history_and_pins():
    directory = history_dir(migration_history_package)
    history = ordered_entries(directory)
    pins = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
    return history, pins


def test_released_history_manifest_matches_raw_packaged_bytes() -> None:
    history, pins = _history_and_pins()
    entries = {entry.name: entry for entry in history}
    assert set(pins) <= set(entries), "digest manifest names a missing entry"
    mismatches = {
        name: (expected, raw_content_sha256(entries[name].path.read_bytes()))
        for name, expected in pins.items()
        if raw_content_sha256(entries[name].path.read_bytes()) != expected
    }
    assert mismatches == {}


def test_validation_database_ledger_matches_raw_packaged_bytes(test_db) -> None:
    history, _pins = _history_and_pins()
    entries = {entry.name: entry for entry in history}
    ledger = {
        str(name): str(digest)
        for name, digest in test_db.execute(
            "SELECT migration_name, content_sha256 FROM applied_migrations "
            "WHERE content_sha256 IS NOT NULL"
        ).fetchall()
    }
    assert set(ledger) <= set(entries), "ledger names a missing packaged entry"
    assert ledger[VALIDATION_LEDGER_ENTRY] == VALIDATION_LEDGER_DIGEST
    mismatches = {
        name: (digest, raw_content_sha256(entries[name].path.read_bytes()))
        for name, digest in ledger.items()
        if name in entries
        and raw_content_sha256(entries[name].path.read_bytes()) != digest
    }
    assert mismatches == {}


def test_released_history_manifest_is_a_complete_frozen_prefix() -> None:
    history, pins = _history_and_pins()
    entries = {entry.name: entry for entry in history}
    highest_frozen = max(entries[name].sequence for name in pins)
    frozen_prefix = {
        entry.name for entry in history if entry.sequence <= highest_frozen
    }
    assert set(pins) == frozen_prefix

    unpinned_cut_floors = []
    for entry in history:
        module = load_migration_module(entry.path, entry.name)
        floor = declared_minimum(module)
        if floor not in {None, NEXT_RELEASE} and entry.name not in pins:
            unpinned_cut_floors.append(entry.name)
    assert unpinned_cut_floors == []
