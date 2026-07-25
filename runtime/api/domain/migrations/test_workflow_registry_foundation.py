"""Governed migration coverage for the additive workflow registry."""

from __future__ import annotations

from yoke_core.domain.migrations.workflow_registry_foundation import (
    apply,
    invariants,
)


def test_apply_and_invariants_are_idempotent(test_db):
    apply(test_db)
    invariants(test_db)
    apply(test_db)
    invariants(test_db)
