"""Coverage for the PathClaimOverride telemetry emitter.

Split out of ``test_path_claims_override.py`` to keep both files
under the 350-line cap. Owns the *event-shape* tests: payload
validation at the emitter and ledger-write smoke. The emitter is
telemetry alongside the ``path_claim_overrides`` state row; fact-layer
behaviour (invoke / is_active / retirement) lives in
``test_path_claims_override.py``.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    conn,
    local_human,
    seed_item,
    seed_target,
)
from yoke_core.domain.path_claims import register
from yoke_core.domain.path_claims_events_override import emit_override


def _override_event_contexts(conn, *, path_claim_id: int) -> list:
    rows = conn.execute(
        "SELECT envelope FROM events "
        "WHERE event_name = 'PathClaimOverride' ORDER BY id ASC"
    ).fetchall()
    out = []
    for row in rows:
        envelope = json.loads(row[0])
        ctx = envelope.get("context") or {}
        if int(ctx.get("path_claim_id", -1)) == int(path_claim_id):
            out.append(ctx)
    return out


class TestEmitOverridePayload:
    """AC-10: payload carries the canonical 8 fields plus conflict_reason."""

    def test_creation_override_minimal_payload(self, conn):
        actor = local_human(conn)
        item_id = seed_item(conn, item_id=23001)
        target = seed_target(conn, path_string="src/foo.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        emit_override(
            conn=conn, path_claim_id=cid, override_point="creation",
            integration_target="main", actor_id=actor,
            actor_reason="cannot reach holder",
            blocking_path_targets=[target], item_id=item_id,
            project="yoke",
        )
        contexts = _override_event_contexts(conn, path_claim_id=cid)
        assert len(contexts) == 1
        ctx = contexts[0]
        for field in (
            "path_claim_id", "override_point", "integration_target",
            "actor_id", "actor_reason", "invoked_at",
            "blocking_path_targets",
        ):
            assert field in ctx, f"missing field {field!r} in payload"
        assert ctx["override_point"] == "creation"
        assert ctx["actor_reason"] == "cannot reach holder"
        assert ctx["blocking_path_targets"] == [target]

    def test_revalidation_conflict_requires_conflict_reason(self, conn):
        actor = local_human(conn)
        item_id = seed_item(conn, item_id=23002)
        target = seed_target(conn, path_string="src/foo.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        with pytest.raises(ValueError, match="conflict_reason"):
            emit_override(
                conn=conn, path_claim_id=cid,
                override_point="revalidation_conflict",
                integration_target="main", actor_id=actor,
                actor_reason="upstream rebased on us",
            )

    def test_invalid_override_point_is_rejected(self, conn):
        with pytest.raises(ValueError, match="override_point"):
            emit_override(
                conn=conn, path_claim_id=1, override_point="garbage",
                integration_target="main", actor_id=1, actor_reason="x",
            )

    def test_empty_actor_reason_is_rejected_in_emitter(self, conn):
        with pytest.raises(ValueError, match="actor_reason"):
            emit_override(
                conn=conn, path_claim_id=1, override_point="creation",
                integration_target="main", actor_id=1, actor_reason="   ",
            )


class TestOverrideStateTable:
    """The override fact is table-backed state, not an events scan."""

    def test_emitter_alone_writes_no_state_row(self, conn):
        """The emitter is pure telemetry — only ``invoke_override``
        lands the gating fact in ``path_claim_overrides``."""
        from yoke_core.domain.path_claims_override import list_overrides

        actor = local_human(conn)
        item_id = seed_item(conn, item_id=23003)
        target = seed_target(conn, path_string="src/bar.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        emit_override(
            conn=conn, path_claim_id=cid, override_point="creation",
            integration_target="main", actor_id=actor,
            actor_reason="telemetry only",
        )
        assert list_overrides(conn, path_claim_id=cid) == []

    def test_override_state_table_exists(self, conn):
        from yoke_core.domain.schema_common import _get_tables

        assert "path_claim_overrides" in set(_get_tables(conn))
