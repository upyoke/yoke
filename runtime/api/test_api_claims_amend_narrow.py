# ruff: noqa: F811

"""Hosted-safe narrowing coverage for ``claims.path.amend``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from runtime.api.domain._path_claims_test_helpers import (  # noqa: F401
    conn,
    local_human,
    seed_target,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.claims_path_amend import handle_amend
from yoke_core.domain.migration_path_claim_widen import MigrationPathClaimContext
from yoke_core.domain.path_claims import get_claim, register
from yoke_core.domain.path_claims_amend import (
    CannotAmendClaim,
    NarrowWouldOrphanCommittedWork,
    narrow,
)


_HEAD = "a" * 40
_LANE = "/client/worktrees/claim-owner"


def _seed_item(conn, *, item_id: int) -> int:
    conn.execute(
        "INSERT INTO items "
        "(id, title, workflow_id, workflow_version_id, status, priority, "
        "created_at, updated_at, project_id, project_sequence) VALUES "
        "(%s, 'item', 'issue', "
        "(SELECT current_version_id FROM workflows WHERE id='issue'), "
        "'idea', 'medium', '2026-08-18T00:00:00Z', "
        "'2026-08-18T00:00:00Z', 1, %s)",
        (item_id, item_id),
    )
    conn.commit()
    return item_id


def _record_lane(conn, *, item_id: int, head_sha: str = _HEAD) -> None:
    from yoke_core.domain.item_worktree_schema import ensure_item_worktree_schema

    ensure_item_worktree_schema(conn)
    conn.execute(
        "INSERT INTO item_worktrees "
        "(item_id, branch, path, commit_sha, lane_role, state, "
        "created_at, updated_at) VALUES "
        "(%s, 'claim-owner', %s, %s, 'implementation', 'active', "
        "'2026-08-18T00:00:00Z', '2026-08-18T00:00:00Z')",
        (item_id, _LANE, head_sha),
    )
    conn.commit()


def _evidence(*, touched_paths: list[str], head_sha: str = _HEAD) -> dict:
    return {
        "repo_root": _LANE,
        "head_sha": head_sha,
        "integration_target": "main",
        "touched_paths": touched_paths,
        "uncommitted_paths": [],
        "rename_pairs": [],
    }


def _claim_with_two_paths(conn, *, item_id: int):
    actor = local_human(conn)
    keep = seed_target(conn, path_string=f"src/{item_id}_keep.py")
    drop = seed_target(conn, path_string=f"src/{item_id}_drop.py")
    claim_id = register(
        conn,
        actor_id=actor,
        integration_target="main",
        target_ids=[keep, drop],
        item_id=item_id,
    )
    return claim_id, keep, drop


def test_relayed_narrow_accepts_evidence_for_synced_lane(conn):
    item_id = _seed_item(conn, item_id=9401)
    claim_id, keep, drop = _claim_with_two_paths(conn, item_id=item_id)
    _record_lane(conn, item_id=item_id)

    amendment_id = narrow(
        conn,
        claim_id=claim_id,
        drop_target_ids=[drop],
        reason="remove unused coverage",
        boundary_evidence=_evidence(touched_paths=[f"src/{item_id}_keep.py"]),
    )

    assert amendment_id > 0
    assert get_claim(conn, claim_id)["target_ids"] == [keep]


def test_relayed_narrow_rejects_dropped_committed_touch(conn):
    item_id = _seed_item(conn, item_id=9402)
    claim_id, _keep, drop = _claim_with_two_paths(conn, item_id=item_id)
    _record_lane(conn, item_id=item_id)

    with pytest.raises(NarrowWouldOrphanCommittedWork) as excinfo:
        narrow(
            conn,
            claim_id=claim_id,
            drop_target_ids=[drop],
            reason="unsafe removal",
            boundary_evidence=_evidence(
                touched_paths=[f"src/{item_id}_drop.py"],
            ),
        )

    assert excinfo.value.offending_paths == [f"src/{item_id}_drop.py"]


def test_relayed_narrow_rejects_unsynced_head(conn):
    item_id = _seed_item(conn, item_id=9403)
    claim_id, _keep, drop = _claim_with_two_paths(conn, item_id=item_id)
    _record_lane(conn, item_id=item_id)

    with pytest.raises(CannotAmendClaim, match="head does not match"):
        narrow(
            conn,
            claim_id=claim_id,
            drop_target_ids=[drop],
            reason="stale evidence",
            boundary_evidence=_evidence(touched_paths=[], head_sha="b" * 40),
        )


def test_never_activated_claim_can_narrow_without_checkout_evidence(conn):
    item_id = _seed_item(conn, item_id=9404)
    claim_id, keep, drop = _claim_with_two_paths(conn, item_id=item_id)

    narrow(
        conn,
        claim_id=claim_id,
        drop_target_ids=[drop],
        reason="reconcile frozen plan",
    )

    assert get_claim(conn, claim_id)["target_ids"] == [keep]


def test_never_activated_claim_ignores_evidence_from_callers_checkout(conn):
    item_id = _seed_item(conn, item_id=9406)
    claim_id, keep, drop = _claim_with_two_paths(conn, item_id=item_id)
    evidence = _evidence(touched_paths=[])
    evidence["repo_root"] = "/client/worktrees/upstream-item"

    narrow(
        conn,
        claim_id=claim_id,
        drop_target_ids=[drop],
        reason="upstream work lands first",
        boundary_evidence=evidence,
    )

    assert get_claim(conn, claim_id)["target_ids"] == [keep]


def _request(payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="claims.path.amend",
        actor=ActorContext(actor_id="operator", session_id="session-1"),
        target=TargetRef(kind="item", item_id=9405),
        payload=payload,
    )


def test_amend_handler_routes_remove_paths_to_narrowing_domain():
    connection = MagicMock()
    connection.__enter__.return_value = connection
    context = MigrationPathClaimContext(
        item_id=9405,
        project_id=1,
        project="yoke",
        profile_raw='{"state":"none"}',
        attestation_raw="{}",
    )
    payload = {
        "claim_id": 301,
        "remove_paths": ["src/unused.py"],
        "reason": "remove unused path",
        "boundary_evidence": _evidence(touched_paths=[]),
    }
    with (
        patch(
            "yoke_core.domain.db_helpers.connect",
            return_value=connection,
        ),
        patch(
            "yoke_core.domain.migration_path_claim_widen.lock_claim_for_widen",
            return_value=context,
        ),
        patch(
            "yoke_core.domain.path_claims_resolve.resolve_paths_to_target_ids",
            return_value=[41],
        ),
        patch(
            "yoke_core.domain.path_claims_amend.narrow",
            return_value=77,
        ) as narrow_call,
        patch(
            "yoke_core.domain.path_claims_read.claim_projection",
            return_value={"id": 301, "owner_item_id": 9405},
        ),
        patch("yoke_core.domain.path_claims_events.emit_amended"),
    ):
        outcome = handle_amend(_request(payload))

    assert outcome.primary_success is True
    assert outcome.result_payload == {
        "amendment_id": 77,
        "amendment_kind": "narrow",
        "migration_model": None,
        "migration_lease_id": None,
        "db_claim_event_id": None,
    }
    assert narrow_call.call_args.kwargs["drop_target_ids"] == [41]
    assert narrow_call.call_args.kwargs["boundary_evidence"]["head_sha"] == _HEAD


def test_amend_handler_rejects_mixed_add_and_remove_payload():
    outcome = handle_amend(
        _request(
            {
                "claim_id": 301,
                "add_paths": ["src/new.py"],
                "remove_paths": ["src/old.py"],
                "reason": "ambiguous",
            }
        )
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"
