# ruff: noqa: F811

"""Widen classifies overlap only for the paths it adds.

An active claim that already shares a path with an upstream claim, and
later gains an unsatisfied serial edge to that upstream, still widens
with paths that overlap nothing. A new path that does overlap the
upstream still refuses, and the refusal names that path and claim.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.domain._path_claims_test_helpers import (
    DEPENDENCY_FIXTURE_DDL as _DEP_DDL,
    seed_item as _seed_item,
    SNAP,
    conn,  # noqa: F401
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims import (
    IncompatibleOverlap,
    activate,
    get_claim,
    register,
)
from yoke_core.domain.path_claims_amend import widen


def _register(conn, *, item_id: int, target_ids, human_id: int) -> int:
    return register(
        conn,
        actor_id=human_id,
        target_ids=list(target_ids),
        integration_target="main",
        mode="exclusive",
        item_id=item_id,
    )


def _add_edge(conn, *, dependent: int, blocking: int, gate_point: str) -> None:
    conn.execute(_DEP_DDL)
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item_id, blocking_item_id, "
        "gate_point, satisfaction, source, rationale, created_at) "
        "VALUES (%s, %s, %s, 'fact:merged', 'test', 'ordering', "
        "'2026-05-01T00:00:00Z')",
        (dependent, blocking, gate_point),
    )
    conn.commit()


def _active_claim_with_preexisting_serial_overlap(conn):
    """Candidate active on a path the upstream also claims under a
    coordination_only attestation; the serial integration edge
    candidate -> upstream is authored only after both claims exist.
    """
    human = local_human(conn)
    upstream_item = _seed_item(conn, item_id=4601)
    candidate_item = _seed_item(conn, item_id=4602)
    _add_edge(
        conn,
        dependent=candidate_item,
        blocking=upstream_item,
        gate_point="coordination_only",
    )
    shared = seed_target(conn, path_string="n/shared.py")
    upstream_only = seed_target(conn, path_string="n/upstream_only.py")
    upstream_claim = _register(
        conn,
        item_id=upstream_item,
        target_ids=[shared, upstream_only],
        human_id=human,
    )
    candidate_claim = _register(
        conn, item_id=candidate_item, target_ids=[shared], human_id=human
    )
    activate(conn, claim_id=candidate_claim, base_commit_sha=SNAP)
    _add_edge(
        conn,
        dependent=candidate_item,
        blocking=upstream_item,
        gate_point="integration",
    )
    assert get_claim(conn, candidate_claim)["state"] == "active"
    return human, candidate_claim, upstream_claim, upstream_only


def test_widen_with_disjoint_new_paths_succeeds_despite_preexisting_overlap(
    conn,
):
    _, candidate_claim, upstream_claim, _ = (
        _active_claim_with_preexisting_serial_overlap(conn)
    )
    fresh_a = seed_target(conn, path_string="n/fresh_a.py")
    fresh_b = seed_target(conn, path_string="n/fresh_b.py")

    amendment_id = widen(
        conn,
        claim_id=candidate_claim,
        add_target_ids=[fresh_a, fresh_b],
        reason="add independent files",
    )

    assert get_claim(conn, candidate_claim)["state"] == "active"
    payload = json.loads(
        conn.execute(
            "SELECT payload FROM path_claim_amendments WHERE id = %s",
            (amendment_id,),
        ).fetchone()[0]
    )
    assert payload["added"] == [fresh_a, fresh_b]
    assert "serial_upstream_claim_ids" not in payload
    # The pre-existing shared path stays visible for audit only.
    assert payload["overlapping_claim_ids"] == [upstream_claim]


def test_widen_with_new_path_overlapping_upstream_refuses_naming_it(conn):
    _, candidate_claim, upstream_claim, upstream_only = (
        _active_claim_with_preexisting_serial_overlap(conn)
    )
    fresh = seed_target(conn, path_string="n/fresh.py")

    with pytest.raises(IncompatibleOverlap) as excinfo:
        widen(
            conn,
            claim_id=candidate_claim,
            add_target_ids=[fresh, upstream_only],
            reason="add a file the upstream holds",
        )

    msg = str(excinfo.value)
    assert f"claim {upstream_claim} <- new path(s) 'n/upstream_only.py'" in msg
    assert "n/fresh.py" not in msg
    assert "n/shared.py" not in msg
    assert get_claim(conn, candidate_claim)["state"] == "active"
    inserted = conn.execute(
        "SELECT COUNT(*) FROM path_claim_targets WHERE claim_id = %s",
        (candidate_claim,),
    ).fetchone()[0]
    assert inserted == 1
