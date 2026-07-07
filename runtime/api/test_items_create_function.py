"""Coverage for the ``items.create`` function-call surface.

``items.create`` is the wrapped, https-capable idea-intake create path
(``yoke items create``): it lets ``/yoke idea`` create a backlog item
over a prod-https control plane where the local ``db_router items add``
path cannot run. The handler delegates to
:func:`yoke_core.domain.backlog_create_op.execute_create`, so the
``ticket_intake_provenance`` gate still applies — the handler only
threads ``provenance`` through and maps the result to a HandlerOutcome.

The tests below cover: registration + authz classification (PROJECT
scope, ``items.write``, no claim), provenance threading, source-actor
precedence, result/error mapping, and one end-to-end create through the
real ``execute_create`` against a disposable DB.
"""

from __future__ import annotations

import io
import os
from unittest import mock

from runtime.api.backlog_mutations_test_helpers import (
    _item_field,
    _patch_externals,
    tmp_db,  # noqa: F401 — re-exported pytest fixture
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.items_create import handle_item_create
from yoke_core.domain.ticket_intake_provenance import (
    BYPASS_MESSAGE,
    IDEA_INTAKE_ENV,
)


_FUNCTION_ID = "items.create"


def _request(payload, *, session_id="items-create-test", actor_id=None):
    return FunctionCallRequest(
        function=_FUNCTION_ID,
        actor=ActorContext(session_id=session_id, actor_id=actor_id),
        target=TargetRef(kind="global"),
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Registration + authorization classification
# ---------------------------------------------------------------------------


class TestItemsCreateRegistration:
    def test_registered_after_register_all_handlers(self):
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain.yoke_function_registry import lookup

        register_all_handlers()
        entry = lookup(_FUNCTION_ID)
        assert entry is not None, (
            "items.create must register through "
            "yoke_core.domain.handlers.__init_register__"
        )
        # No pre-existing item to claim → no claim gate.
        assert entry.claim_required_kind is None
        assert "global" in entry.target_kinds

    def test_authz_is_project_scoped_items_write(self):
        from yoke_core.domain.actor_permissions import PERM_ITEMS_WRITE
        from yoke_core.domain.function_authz_scope import (
            PROJECT,
            classify,
            permission_key_for,
        )
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain.yoke_function_registry import lookup

        register_all_handlers()
        entry = lookup(_FUNCTION_ID)
        spec = classify(
            _FUNCTION_ID,
            side_effects=bool(entry.side_effects),
            project_permission=permission_key_for(entry),
        )
        # A token actor needs items.write on the TARGET project (resolved
        # from payload["project"]) — not a control-plane or org grant.
        assert spec.scope == PROJECT
        assert spec.permission_key == PERM_ITEMS_WRITE


# ---------------------------------------------------------------------------
# Handler logic (execute_create mocked — exercises only the new handler)
# ---------------------------------------------------------------------------


class TestItemsCreateHandler:
    def test_provenance_threaded_through(self, monkeypatch):
        captured = {}

        def _record(**kwargs):
            captured.update(kwargs)
            return {"success": True, "item_id": 7}

        monkeypatch.setattr(
            "yoke_core.domain.backlog_create_op.execute_create", _record,
        )
        outcome = handle_item_create(
            _request({"title": "T", "type": "issue", "provenance": "idea"}),
        )
        assert outcome.primary_success is True
        assert captured["provenance"] == "idea"
        assert outcome.result_payload["item_id"] == 7

    def test_token_actor_used_as_source(self, monkeypatch):
        captured = {}

        def _record(**kwargs):
            captured.update(kwargs)
            return {"success": True, "item_id": 1}

        monkeypatch.setattr(
            "yoke_core.domain.backlog_create_op.execute_create", _record,
        )
        handle_item_create(
            _request(
                {"title": "T", "type": "issue", "provenance": "idea"},
                actor_id="42",
            ),
        )
        # No explicit payload source → the verified token actor is the source.
        assert captured["source"] == "42"

    def test_explicit_source_wins_over_token_actor(self, monkeypatch):
        captured = {}

        def _record(**kwargs):
            captured.update(kwargs)
            return {"success": True, "item_id": 1}

        monkeypatch.setattr(
            "yoke_core.domain.backlog_create_op.execute_create", _record,
        )
        handle_item_create(
            _request(
                {"title": "T", "type": "issue", "provenance": "idea",
                 "source": "7"},
                actor_id="42",
            ),
        )
        assert captured["source"] == "7"

    def test_missing_provenance_maps_intake_denied(self, monkeypatch):
        def _blocked(**kwargs):
            return {"success": False, "error": BYPASS_MESSAGE}

        monkeypatch.setattr(
            "yoke_core.domain.backlog_create_op.execute_create", _blocked,
        )
        outcome = handle_item_create(_request({"title": "T", "type": "issue"}))
        assert outcome.primary_success is False
        assert outcome.error.code == "intake_denied"
        assert "/yoke idea" in outcome.error.message

    def test_generic_create_failure_maps_create_failed(self, monkeypatch):
        def _fail(**kwargs):
            return {"success": False, "error": "items.source=999 does not match any actors row"}

        monkeypatch.setattr(
            "yoke_core.domain.backlog_create_op.execute_create", _fail,
        )
        outcome = handle_item_create(
            _request({"title": "T", "type": "issue", "provenance": "idea"}),
        )
        assert outcome.primary_success is False
        assert outcome.error.code == "create_failed"

    def test_invalid_payload_missing_title(self):
        outcome = handle_item_create(_request({"type": "issue"}))
        assert outcome.primary_success is False
        assert outcome.error.code == "invalid_payload"


# ---------------------------------------------------------------------------
# End-to-end through the real execute_create (disposable DB)
# ---------------------------------------------------------------------------


class TestItemsCreateEndToEnd:
    def test_payload_provenance_creates_a_row(self, tmp_db, monkeypatch):
        # Pure payload-provenance path (the https shape): no env var, the
        # gate passes because the payload carries provenance="idea".
        monkeypatch.delenv(IDEA_INTAKE_ENV, raising=False)
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            outcome = handle_item_create(
                _request(
                    {"title": "Created via items.create", "type": "issue",
                     "provenance": "idea"},
                ),
            )
        assert outcome.primary_success is True, outcome.error
        item_id = outcome.result_payload["item_id"]
        # The public ref (prefix-sequence) is surfaced for downstream steps.
        item_ref = outcome.result_payload["item_ref"]
        assert item_ref and "-" in item_ref, f"item_ref={item_ref!r}"
        # Source resolved to the seeded local human (numeric actor id).
        source = _item_field(tmp_db, item_id, "source")
        assert source.isdigit(), f"source={source!r} must be a numeric actor id"

    def test_missing_provenance_blocked_end_to_end(self, tmp_db, monkeypatch):
        monkeypatch.delenv(IDEA_INTAKE_ENV, raising=False)
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            outcome = handle_item_create(
                _request({"title": "Naive create", "type": "issue"}),
            )
        assert outcome.primary_success is False
        assert outcome.error.code == "intake_denied"
        assert "/yoke idea" in outcome.error.message
