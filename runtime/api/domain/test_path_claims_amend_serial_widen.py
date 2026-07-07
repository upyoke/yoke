"""Regression coverage for dependency-aware widen-overlap handling.

Pins serial-via-dependency widen, un-attested overlap
rejection, coordination-only / candidate-as-blocker
allow-without-block, active-claim downgrade refusal,
and the structured amendment payload (serial_upstream_claim_ids,
overlapping_claim_ids).
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP,
    conn,
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
from yoke_core.domain.path_claims_amend_overlap import (
    WidenOverlapDecision,
    classify_widen_overlap,
)


_DEP_DDL = (
    "CREATE TABLE IF NOT EXISTS item_dependencies ("
    "id INTEGER PRIMARY KEY, dependent_item TEXT NOT NULL, "
    "blocking_item TEXT NOT NULL, "
    "gate_point TEXT NOT NULL DEFAULT 'activation', "
    "satisfaction TEXT NOT NULL DEFAULT 'status:done', "
    "source TEXT NOT NULL, session_id INTEGER, "
    "rationale TEXT NOT NULL DEFAULT '', "
    "evidence_json TEXT NOT NULL DEFAULT '{}', "
    "created_at TEXT NOT NULL)"
)


def _seed_item(conn, item_id: int) -> int:
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, item_id),
    )
    conn.commit()
    return item_id


def _add_dep_edge(
    conn,
    *,
    dependent: int,
    blocking: int,
    gate_point: str = "activation",
    rationale: str = "test ordering",
):
    conn.execute(_DEP_DDL)
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item, blocking_item, "
        "gate_point, satisfaction, source, rationale, created_at) "
        "VALUES (%s, %s, %s, 'status:done', 'test', %s, "
        "'2026-05-01T00:00:00Z')",
        (
            "YOK-" + str(dependent),
            "YOK-" + str(blocking),
            gate_point,
            rationale,
        ),
    )
    conn.commit()


def _register_candidate(
    conn, *, item_id: int, target_ids, human_id: int,
    integration_target: str = "main",
) -> int:
    return register(
        conn, actor_id=human_id, target_ids=list(target_ids),
        integration_target=integration_target, mode="exclusive",
        item_id=item_id,
    )


def _register_upstream(
    conn, *, item_id: int, target_ids, human_id: int,
    activate_it: bool = True, integration_target: str = "main",
) -> int:
    claim_id = register(
        conn, actor_id=human_id, target_ids=list(target_ids),
        integration_target=integration_target, mode="exclusive",
        item_id=item_id,
    )
    if activate_it:
        activate(conn, claim_id=claim_id, base_commit_sha=SNAP)
    return claim_id


def test_widen_serial_dependent_blocks_candidate_with_chosen_upstream(
    conn,
):
    """Planned candidate widens into upstream's coverage with an
    authored ``activation`` dep edge → widen succeeds, candidate moves
    to ``blocked`` with the canonical blocked_reason wording, and the
    amendment payload records both serial upstreams and overlaps.
    """
    human = local_human(conn)
    upstream_item = _seed_item(conn, item_id=4001)
    candidate_item = _seed_item(conn, item_id=4002)
    _add_dep_edge(conn, dependent=candidate_item, blocking=upstream_item)
    shared = seed_target(conn, path_string="a/shared.py")
    extra = seed_target(conn, path_string="a/extra.py")
    upstream_claim = _register_upstream(
        conn, item_id=upstream_item, target_ids=[shared], human_id=human,
    )
    candidate_other = seed_target(conn, path_string="b/other.py")
    candidate_claim = _register_candidate(
        conn,
        item_id=candidate_item,
        target_ids=[candidate_other],
        human_id=human,
    )

    amendment_id = widen(
        conn,
        claim_id=candidate_claim,
        add_target_ids=[shared, extra],
        reason="widen into upstream serial dependency",
    )

    final = get_claim(conn, candidate_claim)
    assert final["state"] == "blocked"
    assert final["blocked_reason"] == (
        f"serial-via-dependency on path_claims.id={upstream_claim}"
    )

    payload_row = conn.execute(
        "SELECT payload FROM path_claim_amendments WHERE id = %s",
        (amendment_id,),
    ).fetchone()
    payload = json.loads(payload_row[0])
    assert payload["added"] == sorted([shared, extra])
    assert payload["serial_upstream_claim_ids"] == [upstream_claim]
    assert upstream_claim in payload["overlapping_claim_ids"]


def test_widen_no_edge_rejects_without_inserting_targets(conn):
    """No-edge same-target overlap → rejects with
    :class:`IncompatibleOverlap` and no target rows or amendment rows
    persist.
    """
    human = local_human(conn)
    upstream_item = _seed_item(conn, item_id=4101)
    candidate_item = _seed_item(conn, item_id=4102)
    shared = seed_target(conn, path_string="c/shared.py")
    upstream_claim = _register_upstream(
        conn, item_id=upstream_item, target_ids=[shared], human_id=human,
    )
    candidate_other = seed_target(conn, path_string="d/other.py")
    candidate_claim = _register_candidate(
        conn,
        item_id=candidate_item,
        target_ids=[candidate_other],
        human_id=human,
    )

    with pytest.raises(IncompatibleOverlap):
        widen(
            conn,
            claim_id=candidate_claim,
            add_target_ids=[shared],
            reason="widen with no dependency evidence",
        )

    # No new target rows for the shared id.
    inserted = conn.execute(
        "SELECT COUNT(*) FROM path_claim_targets "
        "WHERE claim_id = %s AND target_id = %s",
        (candidate_claim, shared),
    ).fetchone()[0]
    assert inserted == 0

    # No amendment row recorded against the candidate.
    amendments = conn.execute(
        "SELECT COUNT(*) FROM path_claim_amendments WHERE claim_id = %s",
        (candidate_claim,),
    ).fetchone()[0]
    assert amendments == 0

    # Candidate state stays whatever register set it to (no downgrade).
    final = get_claim(conn, candidate_claim)
    assert final["state"] in ("planned", "blocked")
    # Upstream untouched.
    upstream = get_claim(conn, upstream_claim)
    assert upstream["state"] == "active"


def test_widen_active_claim_with_new_serial_overlap_rejects(conn):
    """Candidate already at ``state='active'`` is not silently
    downgraded when widen would require waiting on an upstream.
    """
    human = local_human(conn)
    upstream_item = _seed_item(conn, item_id=4201)
    candidate_item = _seed_item(conn, item_id=4202)
    _add_dep_edge(conn, dependent=candidate_item, blocking=upstream_item)
    candidate_target = seed_target(conn, path_string="e/only.py")
    upstream_target = seed_target(conn, path_string="e/upstream.py")
    # Register and activate the candidate first on a disjoint target;
    # then register the upstream on the path we will widen into.
    candidate_claim = register(
        conn,
        actor_id=human,
        target_ids=[candidate_target],
        integration_target="main",
        mode="exclusive",
        item_id=candidate_item,
    )
    activate(conn, claim_id=candidate_claim, base_commit_sha=SNAP)
    upstream_claim = _register_upstream(
        conn,
        item_id=upstream_item,
        target_ids=[upstream_target],
        human_id=human,
    )

    with pytest.raises(IncompatibleOverlap) as excinfo:
        widen(
            conn,
            claim_id=candidate_claim,
            add_target_ids=[upstream_target],
            reason="active claim widens into upstream",
        )
    msg = str(excinfo.value)
    assert "state='active'" in msg
    assert str(upstream_claim) in msg

    final = get_claim(conn, candidate_claim)
    assert final["state"] == "active"
    # Target row not inserted.
    inserted = conn.execute(
        "SELECT COUNT(*) FROM path_claim_targets "
        "WHERE claim_id = %s AND target_id = %s",
        (candidate_claim, upstream_target),
    ).fetchone()[0]
    assert inserted == 0


def test_widen_coordination_only_does_not_block_candidate(conn):
    """Coordination-only edge → widen allowed without changing claim
    state and without recording a serial upstream.
    """
    human = local_human(conn)
    upstream_item = _seed_item(conn, item_id=4301)
    candidate_item = _seed_item(conn, item_id=4302)
    _add_dep_edge(
        conn,
        dependent=candidate_item,
        blocking=upstream_item,
        gate_point="coordination_only",
        rationale="independent edits on shared module",
    )
    shared = seed_target(conn, path_string="f/shared.py")
    upstream_claim = _register_upstream(
        conn, item_id=upstream_item, target_ids=[shared], human_id=human,
    )
    candidate_other = seed_target(conn, path_string="g/other.py")
    candidate_claim = _register_candidate(
        conn,
        item_id=candidate_item,
        target_ids=[candidate_other],
        human_id=human,
    )
    starting_state = get_claim(conn, candidate_claim)["state"]

    amendment_id = widen(
        conn,
        claim_id=candidate_claim,
        add_target_ids=[shared],
        reason="widen with coordination_only overlap",
    )

    final = get_claim(conn, candidate_claim)
    # State must NOT flip to ``blocked`` via coordination-only edge.
    assert final["state"] == starting_state

    payload_row = conn.execute(
        "SELECT payload FROM path_claim_amendments WHERE id = %s",
        (amendment_id,),
    ).fetchone()
    payload = json.loads(payload_row[0])
    assert payload["added"] == [shared]
    # No serial upstream recorded; overlapping claims still surfaced.
    assert "serial_upstream_claim_ids" not in payload
    assert upstream_claim in payload.get("overlapping_claim_ids", [])


def test_classify_widen_overlap_returns_no_overlap_when_disjoint(conn):
    """When the candidate union does not overlap any other claim, the
    helper returns ``allowed=True, block_claim=False`` and records no
    upstream or overlapping ids. Pure-helper test — no widen call.
    """
    human = local_human(conn)
    candidate_item = _seed_item(conn, item_id=4401)
    other_item = _seed_item(conn, item_id=4402)
    target_a = seed_target(conn, path_string="h/a.py")
    target_b = seed_target(conn, path_string="h/b.py")
    _register_upstream(
        conn, item_id=other_item, target_ids=[target_b], human_id=human,
    )
    candidate_claim = _register_candidate(
        conn,
        item_id=candidate_item,
        target_ids=[target_a],
        human_id=human,
    )

    decision = classify_widen_overlap(
        conn,
        claim_id=candidate_claim,
        candidate_target_ids=[target_a],
        integration_target="main",
        candidate_item_id=candidate_item,
        current_claim_state="planned",
    )
    assert isinstance(decision, WidenOverlapDecision)
    assert decision.allowed
    assert decision.block_claim is False
    assert decision.upstream_claim_ids == []
    assert decision.overlapping_claim_ids == []
