"""AC-21 override-effectiveness tests.

When ``path_claims_override.is_active_override(candidate, blocker)``
reports an active override pair, ``classify_overlap`` permits the pair
as ``SERIAL_VIA_DEPENDENCY``. When the override is retired (per the
retirement contract — the override anchors no longer
intersect the blocker's coverage, or either claim reached a terminal
state), the classifier reverts to today's incompatible verdict.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.path_claims_overlap import (
    OverlapClassification,
    classify_overlap,
)
from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP,
    conn,
    local_human,
    seed_target,
)


def _seed_item(conn, *, item_id: int) -> int:
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, item_id),
    )
    conn.commit()
    return item_id


def _seed_claim(
    conn, *, item_id: int, target_id: int, state: str,
) -> int:
    actor = local_human(conn)
    cur = conn.execute(
        "INSERT INTO path_claims "
        "(state, mode, actor_id, item_id, integration_target, registered_at, "
        "activated_at, base_commit_sha) "
        "VALUES (%s, 'exclusive', %s, %s, 'main', "
        "'2026-05-01T00:00:00Z', "
        "CASE WHEN %s='active' THEN '2026-05-01T01:00:00Z' ELSE NULL END, "
        "CASE WHEN %s='active' THEN %s ELSE NULL END) RETURNING id",
        (state, actor, item_id, state, state, SNAP),
    )
    cid = int(cur.fetchone()[0])
    conn.execute(
        "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
        "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
        (cid, target_id),
    )
    conn.commit()
    return cid


class TestOverrideActivePermits:
    def test_active_override_classifies_as_serial(
        self, conn, monkeypatch,
    ):
        target = seed_target(conn, path_string="runtime/api/domain")
        a_item = _seed_item(conn, item_id=6001)
        b_item = _seed_item(conn, item_id=6002)
        a_claim = _seed_claim(
            conn, item_id=a_item, target_id=target, state="active",
        )
        b_claim = _seed_claim(
            conn, item_id=b_item, target_id=target, state="planned",
        )
        from yoke_core.domain import path_claims_override as _override

        def _stub(conn, *, path_claim_id, blocking_claim_id):
            return path_claim_id == b_claim and blocking_claim_id == a_claim

        monkeypatch.setattr(_override, "is_active_override", _stub)

        outcome = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
            phase="register",
            exclude_claim_id=b_claim,
            candidate_item_id=b_item,
        )
        assert outcome is OverlapClassification.SERIAL_VIA_DEPENDENCY


class TestOverrideRetiredReverts:
    def test_retired_override_reverts_to_incompatible(
        self, conn, monkeypatch,
    ):
        target = seed_target(conn, path_string="runtime/api/domain")
        a_item = _seed_item(conn, item_id=6101)
        b_item = _seed_item(conn, item_id=6102)
        _seed_claim(
            conn, item_id=a_item, target_id=target, state="active",
        )
        b_claim = _seed_claim(
            conn, item_id=b_item, target_id=target, state="planned",
        )
        from yoke_core.domain import path_claims_override as _override

        # Stub returns False — override is retired.
        monkeypatch.setattr(
            _override,
            "is_active_override",
            lambda conn, *, path_claim_id, blocking_claim_id: False,
        )

        outcome = classify_overlap(
            conn,
            target_ids=[target],
            integration_target="main",
            phase="register",
            exclude_claim_id=b_claim,
            candidate_item_id=b_item,
        )
        # No dep edge, no active override → incompatible (today's behavior).
        assert outcome is OverlapClassification.INCOMPATIBLE
