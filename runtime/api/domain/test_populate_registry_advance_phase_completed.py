"""Regression: ``AdvancePhaseCompleted`` is registered + rendered.

Sibling test to ``test_populate_registry.py``. Lives in its own file so
adding this regression does not grow the populate-registry pipeline
test file past the authored-file line cap. Proves both the
authoritative-metadata seed entry and the rendered catalog row are in
place after the orchestrator-event slice lands.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.populate_registry_data_authoritative import (
    AUTHORITATIVE_METADATA,
)


def _find_advance_phase_completed():
    for row in AUTHORITATIVE_METADATA:
        if row[0] == "AdvancePhaseCompleted":
            return row
    return None


def test_advance_phase_completed_registered_in_authoritative_metadata():
    """The orchestrator's per-phase audit event is registered."""
    row = _find_advance_phase_completed()
    assert row is not None, (
        "AdvancePhaseCompleted missing from AUTHORITATIVE_METADATA; the "
        "advance implementation-entry orchestrator emits this event and "
        "the registry tuple is required for HC-event-registry-coverage."
    )
    name, kind, event_type, service, severity, description = row
    assert kind == "workflow"
    assert event_type == "advance_phase"
    assert service == "yoke_core.engines.advance_implementation_entry"
    assert severity == "INFO"
    assert "phase" in description.lower()
    assert "duration_ms" in description


def test_event_catalog_includes_advance_phase_completed():
    """``docs/event-catalog.md`` carries the rendered registry row.

    Defends against the regenerate-step being skipped: if the seed entry
    above lands but the catalog is never re-rendered, this test catches
    the drift. Operators regenerate via
    ``python3 -m yoke_core.domain.populate_registry``.
    """
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    catalog = repo_root / "docs" / "event-catalog.md"
    assert catalog.exists(), f"event catalog missing at {catalog}"
    text = catalog.read_text(encoding="utf-8")
    assert "| AdvancePhaseCompleted |" in text, (
        "AdvancePhaseCompleted row missing from docs/event-catalog.md. "
        "Run `python3 -m yoke_core.domain.populate_registry` to "
        "regenerate the catalog after editing the registry seed."
    )
    assert "yoke_core.engines.advance_implementation_entry" in text
