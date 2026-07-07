"""Coverage for path-claim event emission.

Each emit helper accepts a connection and best-effort writes to the
``events`` table. The helpers ignore ImportError on the underlying
:mod:`yoke_core.domain.events` module so minimal-fixture environments
still see the lifecycle behaviour without requiring the full event
infrastructure.

These tests verify (a) the events module is importable, (b) every
required AC-15 event name is registered in the authoritative metadata,
and (c) the on-ramp surfaces emit on success and on failure.
"""

from __future__ import annotations

import pytest

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP,
    conn,
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims_events import (
    emit_activated,
    emit_activation_blocked,
    emit_amended,
    emit_amendment_blocked,
    emit_boundary_blocked,
    emit_boundary_passed,
    emit_cancelled,
    emit_registered,
    emit_registration_blocked,
    emit_released,
)


_REQUIRED_EVENT_NAMES = (
    "PathClaimRegistered",
    "PathClaimActivated",
    "PathClaimAmended",
    "PathClaimReleased",
    "PathClaimCancelled",
    "PathClaimActivationBlocked",
    "PathClaimRegistrationBlocked",
    "PathClaimAmendmentBlocked",
    "PathClaimBoundaryCheckPassed",
    "PathClaimBoundaryCheckBlocked",
    "PathClaimOverride",
)


class TestEventRegistration:
    def test_all_required_events_in_authoritative_metadata(self):
        from yoke_core.domain.populate_registry_data_authoritative import (
            AUTHORITATIVE_METADATA,
        )

        registered_names = {row[0] for row in AUTHORITATIVE_METADATA}
        for name in _REQUIRED_EVENT_NAMES:
            assert name in registered_names, (
                f"{name} missing from AUTHORITATIVE_METADATA"
            )

    def test_event_payload_shape_is_lifecycle_path_claim(self):
        from yoke_core.domain.populate_registry_data_authoritative import (
            AUTHORITATIVE_METADATA,
        )

        for row in AUTHORITATIVE_METADATA:
            if row[0] not in _REQUIRED_EVENT_NAMES:
                continue
            # (name, kind, event_type, service, severity, description)
            assert row[1] == "lifecycle"
            assert row[2] == "path_claim"
            assert row[5]  # description present


class TestEmitHelpers:
    """Each emit helper must be safe to call against a minimal-fixture conn."""

    def test_emit_helpers_do_not_raise_without_events_module(self, conn):
        # The minimal-fixture conn here has no events table; the emit
        # helpers should still complete without raising.
        sample_claim = {
            "id": 1,
            "item_id": 7000,
            "session_id": None,
            "actor_id": 1,
            "integration_target": "main",
            "state": "planned",
            "target_ids": [42],
        }
        # Each helper should return None or a string (event id), never raise.
        for fn, kwargs in (
            (emit_registered, dict(claim=sample_claim)),
            (emit_activated, dict(claim=sample_claim)),
            (emit_released, dict(claim=sample_claim, reason="merged")),
            (emit_cancelled, dict(claim=sample_claim, reason="abandoned")),
            (
                emit_registration_blocked,
                dict(item_id=7000, integration_target="main", reason="overlap"),
            ),
            (
                emit_activation_blocked,
                dict(claim_id=1, integration_target="main", reason="overlap"),
            ),
            (
                emit_amended,
                dict(
                    claim=sample_claim, amendment_id=1,
                    amendment_kind="widen", payload={}, reason="r",
                ),
            ),
            (
                emit_amendment_blocked,
                dict(claim_id=1, amendment_kind="narrow", reason="r"),
            ),
            (
                emit_boundary_passed,
                dict(claim_id=1, integration_target="main", status="valid"),
            ),
            (
                emit_boundary_blocked,
                dict(claim_id=1, integration_target="main", diagnostics="d"),
            ),
        ):
            fn(conn=conn, **kwargs)


class TestRegistrationEmits:
    """register_for_item emits PathClaimRegistered or *Blocked appropriately."""

    def test_register_emits_on_success(self, conn, monkeypatch):
        from yoke_core.domain import path_claims_register

        emitted = []

        def _capture(*, conn, claim, project=None):
            emitted.append(("registered", claim["id"]))
            return "evt-1"

        monkeypatch.setattr(
            path_claims_register, "register_for_item",
            path_claims_register.register_for_item,
        )
        # Patch the module-local import inside register_for_item via the
        # parent events module attribute so the captured emit fires.
        from yoke_core.domain import path_claims_events

        monkeypatch.setattr(path_claims_events, "emit_registered", _capture)

        actor = local_human(conn)
        target = seed_target(conn, path_string="src/foo.py")
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, "
            "created_at, updated_at, project_id, project_sequence) "
            "VALUES (12001, 't', 'issue', 'idea', 'medium', "
            "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, 12001)",
        )
        conn.commit()
        path_claims_register.register_for_item(
            conn,
            item_id=12001,
            integration_target="main",
            paths=["src/foo.py"],
            actor_id=actor,
        )
        assert emitted and emitted[0][0] == "registered"

    def test_register_emits_blocked_on_overlap(self, conn, monkeypatch):
        from yoke_core.domain import path_claims_events, path_claims_register
        from yoke_core.domain.path_claims import (
            activate, register as raw_register,
        )

        emitted = []

        def _capture_blocked(*, conn, **kwargs):
            emitted.append(("blocked", kwargs))
            return "evt-2"

        monkeypatch.setattr(
            path_claims_events, "emit_registration_blocked", _capture_blocked,
        )

        actor = local_human(conn)
        target = seed_target(conn, path_string="src/foo.py")
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, "
            "created_at, updated_at, project_id, project_sequence) "
            "VALUES (12101, 't', 'issue', 'idea', 'medium', "
            "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, 12101)",
        )
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, "
            "created_at, updated_at, project_id, project_sequence) "
            "VALUES (12102, 't', 'issue', 'idea', 'medium', "
            "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, 12102)",
        )
        conn.commit()
        cid = raw_register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=12101,
        )
        activate(conn, claim_id=cid, base_commit_sha=SNAP)
        with pytest.raises(Exception):
            path_claims_register.register_for_item(
                conn,
                item_id=12102,
                integration_target="main",
                paths=["src/foo.py"],
                actor_id=actor,
            )
        assert emitted and emitted[0][0] == "blocked"


class TestActivationWrapperEmits:
    def test_activate_with_events_emits_activated(self, conn, monkeypatch):
        from yoke_core.domain import path_claims_events, path_claims_register
        from yoke_core.domain.path_claims import register as raw_register

        emitted = []
        monkeypatch.setattr(
            path_claims_events, "emit_activated",
            lambda *, conn, claim, project=None: emitted.append(claim["id"]),
        )
        actor = local_human(conn)
        target = seed_target(conn, path_string="src/foo.py")
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, "
            "created_at, updated_at, project_id, project_sequence) "
            "VALUES (12201, 't', 'issue', 'idea', 'medium', "
            "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, 12201)",
        )
        conn.commit()
        cid = raw_register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=12201,
        )
        path_claims_register.activate_with_events(
            conn, claim_id=cid, base_commit_sha=SNAP,
        )
        assert emitted == [cid]
