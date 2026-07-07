"""Register-side tests for the path-claim domain.

Lifecycle (activate/release/cancel) and overlap-classifier coverage
live in ``test_path_claims_lifecycle.py`` and
``test_path_claims_overlap.py``. The shared ``conn`` fixture and
``seed_target`` / ``local_human`` helpers are imported from
``_path_claims_test_helpers`` so all three files exercise the same
schema substrate.
"""

from __future__ import annotations

import pytest

from yoke_core.domain._path_claims_test_helpers import (
    conn,  # noqa: F401  (pytest fixture)
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims import (
    IncompatibleOverlap,
    InvalidActor,
    InvalidMode,
    InvalidTargetSet,
    get_claim,
    register,
)


class TestRegister:
    def test_register_planned_with_no_overlap(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        claim_id = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
        )
        claim = get_claim(conn, claim_id)
        assert claim["state"] == "planned"
        assert claim["mode"] == "exclusive"
        assert claim["actor_id"] == actor
        assert claim["target_ids"] == [target]

    def test_register_rejects_unknown_actor(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        with pytest.raises(InvalidActor):
            register(
                conn,
                actor_id=424242,
                integration_target="main",
                target_ids=[target],
            )

    def test_register_rejects_parallel_mode(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        with pytest.raises(InvalidMode, match="parallel"):
            register(
                conn,
                actor_id=actor,
                integration_target="main",
                target_ids=[target],
                mode="parallel",
            )

    def test_register_rejects_unknown_mode(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        with pytest.raises(InvalidMode, match="unknown mode"):
            register(
                conn,
                actor_id=actor,
                integration_target="main",
                target_ids=[target],
                mode="advisory",
            )

    def test_register_rejects_empty_target_set(self, conn):
        actor = local_human(conn)
        with pytest.raises(InvalidTargetSet, match="at least one"):
            register(
                conn,
                actor_id=actor,
                integration_target="main",
                target_ids=[],
            )

    def test_register_rejects_unknown_target_id(self, conn):
        actor = local_human(conn)
        with pytest.raises(InvalidTargetSet, match="do not exist"):
            register(
                conn,
                actor_id=actor,
                integration_target="main",
                target_ids=[424242],
            )

    def test_register_blocks_when_serial_upstream_named(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        upstream = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
        )
        downstream = register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            upstream_claim_id=upstream,
        )
        claim = get_claim(conn, downstream)
        assert claim["state"] == "blocked"
        assert "serial-via-dependency" in claim["blocked_reason"]

    def test_register_rejects_incompatible_overlap_without_dependency(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
        )
        with pytest.raises(IncompatibleOverlap):
            register(
                conn,
                actor_id=actor,
                integration_target="main",
                target_ids=[target],
            )

    def test_register_disjoint_targets_do_not_overlap(self, conn):
        actor = local_human(conn)
        a = seed_target(conn, path_string="runtime/api/domain")
        b = seed_target(conn, path_string="runtime/harness")
        register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[a],
        )
        register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[b],
        )

    def test_register_different_integration_targets_are_independent(self, conn):
        actor = local_human(conn)
        target = seed_target(conn, path_string="runtime/api/domain")
        register(
            conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
        )
        register(
            conn,
            actor_id=actor,
            integration_target="release/2026.06",
            target_ids=[target],
        )
