"""Path-integrity regression fixtures — public catalog.

Materializes named substrate states that the path-integrity verifier
must catch. Per-fixture seeding implementations live in
:mod:`yoke_core.domain.path_integrity_fixtures_seed`; this module is
the only sanctioned import path for callers (tests, CLIs).

Each fixture writes its substrate rows directly and records a row in
``path_integrity_fixtures`` capturing the fixture's name, the project
it seeded, and (for known-bad fixtures) the invariant the fixture is
expected to trip. Tests assert that loading a fixture by name causes
the named invariant to fail deterministically — this is the module's
core contract.

Fixture catalog:

* ``clean_v1`` — minimal coherent substrate; verifier passes.
* ``duplicate_identity_v1`` — duplicate ``path_targets`` identity.
* ``incoherent_parent_child_v1`` — cross-project parent reference.
* ``broken_snapshot_idempotency_v1`` — duplicate snapshots disagree.
* ``ambiguous_continuity_v1`` — multiple outbound ``path_moves``.
* ``conflicting_context_inheritance_v1`` — conflicting
  continuity-projected ``path_context_values``.
* ``substrate_drift_v1`` — a snapshot entry references another
  project's target.

Fixtures are pure: every fixture function takes a database connection,
writes the substrate, and returns the new ``path_integrity_fixtures.id``.
The connection's commit semantics are the caller's responsibility.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

from yoke_core.domain.path_integrity_fixtures_seed import (
    fixture_ambiguous_continuity_v1,
    fixture_broken_snapshot_idempotency_v1,
    fixture_clean_v1,
    fixture_conflicting_context_inheritance_v1,
    fixture_duplicate_identity_v1,
    fixture_incoherent_parent_child_v1,
    fixture_substrate_drift_v1,
)
from yoke_core.domain.path_integrity_invariants import (
    INVARIANT_CONTEXT_INHERITANCE,
    INVARIANT_CONTINUITY_DETERMINISM,
    INVARIANT_DRIFT,
    INVARIANT_DUPLICATE_IDENTITY,
    INVARIANT_PARENT_CHILD,
    INVARIANT_SNAPSHOT_IDEMPOTENCY,
)


_FIXTURES: Dict[str, Callable[[Any, str], int]] = {
    "clean_v1": fixture_clean_v1,
    "duplicate_identity_v1": fixture_duplicate_identity_v1,
    "incoherent_parent_child_v1": fixture_incoherent_parent_child_v1,
    "broken_snapshot_idempotency_v1": fixture_broken_snapshot_idempotency_v1,
    "ambiguous_continuity_v1": fixture_ambiguous_continuity_v1,
    "conflicting_context_inheritance_v1":
        fixture_conflicting_context_inheritance_v1,
    "substrate_drift_v1": fixture_substrate_drift_v1,
}


_DEFAULT_PROJECT_IDS: Dict[str, str] = {
    "clean_v1": "fix_clean",
    "duplicate_identity_v1": "fix_dupe",
    "incoherent_parent_child_v1": "fix_pc",
    "broken_snapshot_idempotency_v1": "fix_idem",
    "ambiguous_continuity_v1": "fix_cont",
    "conflicting_context_inheritance_v1": "fix_ctx",
    "substrate_drift_v1": "fix_drift",
}


def available_fixtures() -> Tuple[str, ...]:
    return tuple(sorted(_FIXTURES))


def load_fixture(
    conn: Any,
    name: str,
    *,
    project_id: Optional[str] = None,
) -> int:
    """Load the named fixture into ``conn`` and return its
    ``path_integrity_fixtures.id``.

    Raises :class:`KeyError` for unknown fixture names — callers must
    pre-validate against :func:`available_fixtures`. The default
    ``project_id`` for each fixture is intentionally fixture-specific
    so isolated fixtures can coexist in one DB; callers needing a
    custom id may override.
    """
    if name not in _FIXTURES:
        raise KeyError(
            f"unknown fixture {name!r}; available: "
            f"{', '.join(available_fixtures())}"
        )
    func = _FIXTURES[name]
    if project_id is None:
        return func(conn, _DEFAULT_PROJECT_IDS[name])
    return func(conn, project_id)


__all__ = [
    "INVARIANT_CONTEXT_INHERITANCE",
    "INVARIANT_CONTINUITY_DETERMINISM",
    "INVARIANT_DRIFT",
    "INVARIANT_DUPLICATE_IDENTITY",
    "INVARIANT_PARENT_CHILD",
    "INVARIANT_SNAPSHOT_IDEMPOTENCY",
    "available_fixtures",
    "fixture_ambiguous_continuity_v1",
    "fixture_broken_snapshot_idempotency_v1",
    "fixture_clean_v1",
    "fixture_conflicting_context_inheritance_v1",
    "fixture_duplicate_identity_v1",
    "fixture_incoherent_parent_child_v1",
    "fixture_substrate_drift_v1",
    "load_fixture",
]
