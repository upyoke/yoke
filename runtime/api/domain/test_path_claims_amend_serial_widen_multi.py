"""Multi-upstream determinism + mutation-clean rejection coverage.

Lives in a sibling file because ``test_path_claims_amend_serial_widen.py``
already sits near the 350-line cap. Covers:

- AC-11: with two authored serial upstreams competing on the widened
  union, the amendment payload records both ``serial_upstream_claim_ids``
  and ``overlapping_claim_ids`` deterministically (sorted).
- AC-12: ambiguous helper evidence (no authored dep edge against an
  overlapping party) rejects before any mutation lands — no target rows,
  no claim-state change, no amendment row.
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
):
    conn.execute(_DEP_DDL)
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item, blocking_item, "
        "gate_point, satisfaction, source, rationale, created_at) "
        "VALUES (%s, %s, %s, 'status:done', 'test', 'multi-upstream', "
        "'2026-05-01T00:00:00Z')",
        ("YOK-" + str(dependent), "YOK-" + str(blocking), gate_point),
    )
    conn.commit()


def test_widen_records_all_serial_upstreams_and_overlaps(conn):
    """AC-11: two attested serial upstreams → payload records both ids in
    sorted order; ``serial_upstream_claim_ids`` and
    ``overlapping_claim_ids`` are deterministic.
    """
    human = local_human(conn)
    upstream_a = _seed_item(conn, item_id=4501)
    upstream_b = _seed_item(conn, item_id=4502)
    candidate = _seed_item(conn, item_id=4503)
    _add_dep_edge(conn, dependent=candidate, blocking=upstream_a)
    _add_dep_edge(conn, dependent=candidate, blocking=upstream_b)

    shared_a = seed_target(conn, path_string="m/shared_a.py")
    shared_b = seed_target(conn, path_string="m/shared_b.py")
    claim_a = register(
        conn, actor_id=human, target_ids=[shared_a],
        integration_target="main", mode="exclusive", item_id=upstream_a,
    )
    activate(conn, claim_id=claim_a, base_commit_sha=SNAP)
    claim_b = register(
        conn, actor_id=human, target_ids=[shared_b],
        integration_target="main", mode="exclusive", item_id=upstream_b,
    )
    activate(conn, claim_id=claim_b, base_commit_sha=SNAP)

    candidate_other = seed_target(conn, path_string="m/only.py")
    candidate_claim = register(
        conn, actor_id=human, target_ids=[candidate_other],
        integration_target="main", mode="exclusive", item_id=candidate,
    )

    amendment_id = widen(
        conn,
        claim_id=candidate_claim,
        add_target_ids=[shared_a, shared_b],
        reason="widen into both attested upstreams",
    )

    final = get_claim(conn, candidate_claim)
    assert final["state"] == "blocked"
    # Blocked reason names ONE chosen upstream (the deterministic pick).
    # The payload still records both serial upstreams + overlaps.
    payload_row = conn.execute(
        "SELECT payload FROM path_claim_amendments WHERE id = %s",
        (amendment_id,),
    ).fetchone()
    payload = json.loads(payload_row[0])
    assert payload["added"] == sorted([shared_a, shared_b])
    serial = payload["serial_upstream_claim_ids"]
    overlapping = payload["overlapping_claim_ids"]
    assert sorted(serial) == sorted([claim_a, claim_b])
    assert sorted(overlapping) == sorted([claim_a, claim_b])
    # Ordering is deterministic (sorted ascending) so future readers can
    # compare payloads across runs without spurious diffs.
    assert serial == sorted(serial)
    assert overlapping == sorted(overlapping)


def test_widen_mixed_evidence_rejects_mutation_clean(conn):
    """AC-12: when the widened union overlaps two claims but only one has
    an authored dep edge, the helper rejects before any mutation lands —
    no new target rows, no claim-state change, no amendment row.
    """
    human = local_human(conn)
    attested_upstream = _seed_item(conn, item_id=4601)
    silent_upstream = _seed_item(conn, item_id=4602)
    candidate = _seed_item(conn, item_id=4603)
    _add_dep_edge(conn, dependent=candidate, blocking=attested_upstream)
    # No edge against silent_upstream — that overlap is un-attested.

    shared_attested = seed_target(conn, path_string="x/attested.py")
    shared_silent = seed_target(conn, path_string="x/silent.py")
    claim_attested = register(
        conn, actor_id=human, target_ids=[shared_attested],
        integration_target="main", mode="exclusive",
        item_id=attested_upstream,
    )
    activate(conn, claim_id=claim_attested, base_commit_sha=SNAP)
    claim_silent = register(
        conn, actor_id=human, target_ids=[shared_silent],
        integration_target="main", mode="exclusive",
        item_id=silent_upstream,
    )
    activate(conn, claim_id=claim_silent, base_commit_sha=SNAP)

    candidate_other = seed_target(conn, path_string="x/only.py")
    candidate_claim = register(
        conn, actor_id=human, target_ids=[candidate_other],
        integration_target="main", mode="exclusive", item_id=candidate,
    )
    starting_state = get_claim(conn, candidate_claim)["state"]

    with pytest.raises(IncompatibleOverlap):
        widen(
            conn,
            claim_id=candidate_claim,
            add_target_ids=[shared_attested, shared_silent],
            reason="mixed evidence widen attempt",
        )

    # Mutation-clean: no new target rows for either shared id.
    inserted = conn.execute(
        "SELECT COUNT(*) FROM path_claim_targets "
        "WHERE claim_id = %s AND target_id IN (%s, %s)",
        (candidate_claim, shared_attested, shared_silent),
    ).fetchone()[0]
    assert inserted == 0

    # No amendment row recorded against the candidate.
    amendments = conn.execute(
        "SELECT COUNT(*) FROM path_claim_amendments WHERE claim_id = %s",
        (candidate_claim,),
    ).fetchone()[0]
    assert amendments == 0

    # Candidate state unchanged; both upstreams still active.
    final = get_claim(conn, candidate_claim)
    assert final["state"] == starting_state
    assert get_claim(conn, claim_attested)["state"] == "active"
    assert get_claim(conn, claim_silent)["state"] == "active"
