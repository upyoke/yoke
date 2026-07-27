"""Coverage for the ``items.create`` function-call surface.

``items.create`` is the wrapped, HTTPS-capable work-item create path
(``yoke items create``): it lets a harness skill create an item
over a prod-https control plane where the local ``db_router items add``
path cannot run. The handler delegates to
:func:`yoke_core.domain.backlog_create_op.execute_create`, so the
workflow entry-surface gate still applies.

The tests below cover: registration + authz classification (PROJECT
scope, ``items.write``, no claim), entry-surface threading, source-actor
precedence, result/error mapping, and one end-to-end create through the
real ``execute_create`` against a disposable DB.
"""

from __future__ import annotations

import os
from unittest import mock

from runtime.api.backlog_mutations_test_helpers import (
    _conn,
    _item_field,
    _patch_externals,
    tmp_db,  # noqa: F401 — re-exported pytest fixture
)
from runtime.api.qa_catalog_test_support import CATALOG_CASES
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.items_create import handle_item_create
from yoke_core.domain.item_entry_surface import (
    ITEM_ENTRY_SURFACE_ENV,
    MISSING_ENTRY_SURFACE_MESSAGE,
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
    def test_entry_surface_threaded_through(self, monkeypatch):
        captured = {}

        def _record(**kwargs):
            captured.update(kwargs)
            return {"success": True, "item_id": 7}

        monkeypatch.setattr(
            "yoke_core.domain.backlog_create_op.execute_create", _record,
        )
        outcome = handle_item_create(
            _request({
                "title": "T",
                "workflow": "issue",
                "entry_surface": "harness_skill",
            }),
        )
        assert outcome.primary_success is True
        assert captured["entry_surface"] == "harness_skill"
        assert captured["workflow_posture"] == {}
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
                {
                    "title": "T",
                    "workflow": "issue",
                    "entry_surface": "harness_skill",
                },
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
                {"title": "T", "workflow": "issue",
                 "entry_surface": "harness_skill",
                 "source": "7"},
                actor_id="42",
            ),
        )
        assert captured["source"] == "7"

    def test_missing_entry_surface_maps_denial(self, monkeypatch):
        def _blocked(**kwargs):
            return {"success": False, "error": MISSING_ENTRY_SURFACE_MESSAGE}

        monkeypatch.setattr(
            "yoke_core.domain.backlog_create_op.execute_create", _blocked,
        )
        outcome = handle_item_create(
            _request({"title": "T", "workflow": "issue"}),
        )
        assert outcome.primary_success is False
        assert outcome.error.code == "entry_surface_denied"
        assert "typed entry surface" in outcome.error.message

    def test_generic_create_failure_maps_create_failed(self, monkeypatch):
        def _fail(**kwargs):
            return {"success": False, "error": "items.source=999 does not match any actors row"}

        monkeypatch.setattr(
            "yoke_core.domain.backlog_create_op.execute_create", _fail,
        )
        outcome = handle_item_create(
            _request({
                "title": "T",
                "workflow": "issue",
                "entry_surface": "harness_skill",
            }),
        )
        assert outcome.primary_success is False
        assert outcome.error.code == "create_failed"

    def test_invalid_payload_missing_title(self):
        outcome = handle_item_create(_request({"workflow": "issue"}))
        assert outcome.primary_success is False
        assert outcome.error.code == "invalid_payload"


# ---------------------------------------------------------------------------
# End-to-end through the real execute_create (disposable DB)
# ---------------------------------------------------------------------------


class TestItemsCreateEndToEnd:
    def test_plan_posture_creates_item_attachment_at_dash_review(
        self, tmp_db, monkeypatch,  # noqa: F811
    ):
        from yoke_core.domain.qa_catalog_schema import (
            create_qa_catalog_tables,
        )
        from yoke_core.domain.qa_plan_management import (
            create_plan,
            replace_plan_cases,
        )

        conn = _conn(tmp_db)
        try:
            create_qa_catalog_tables(conn)
            plan = create_plan(
                conn,
                project="yoke",
                slug="dash-close",
                name="Dash close",
            )
            replace_plan_cases(
                conn, plan_id=plan["id"], cases=[CATALOG_CASES[0]],
            )
        finally:
            conn.close()

        monkeypatch.delenv(ITEM_ENTRY_SURFACE_ENV, raising=False)
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            outcome = handle_item_create(
                _request({
                    "title": "Fix the footer",
                    "instruction": "Correct the footer and verify every link.",
                    "workflow": "dash",
                    "project": "yoke",
                    "entry_surface": "web_form",
                    "workflow_posture": {
                        "verification": {
                            "kind": "plan",
                            "plan_id": plan["id"],
                        },
                    },
                }),
            )

        assert outcome.primary_success is True, outcome.error
        item_id = int(outcome.result_payload["item_id"])
        conn = _conn(tmp_db)
        try:
            attachment = conn.execute(
                "SELECT plan_id, transition_id, qa_phase "
                "FROM qa_plan_item_attachments WHERE item_id=%s",
                (item_id,),
            ).fetchone()
            requirement_count = conn.execute(
                "SELECT COUNT(*) FROM qa_requirements WHERE item_id=%s",
                (item_id,),
            ).fetchone()[0]
        finally:
            conn.close()

        assert int(attachment["plan_id"]) == int(plan["id"])
        assert attachment["transition_id"] == "reviewing-implementation"
        assert attachment["qa_phase"] == "verification"
        assert int(requirement_count) == 0

    def test_web_form_create_stores_instruction_and_posture_atomically(
        self, tmp_db, monkeypatch,  # noqa: F811
    ):
        monkeypatch.delenv(ITEM_ENTRY_SURFACE_ENV, raising=False)
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            outcome = handle_item_create(
                _request({
                    "title": "Fix the footer",
                    "instruction": "Correct the footer and verify every link.",
                    "workflow": "dash",
                    "project": "yoke",
                    "entry_surface": "web_form",
                    "workflow_posture": {
                        "path_claims": True,
                        "approval_on_done": True,
                    },
                }),
            )
        assert outcome.primary_success is True, outcome.error
        item_id = outcome.result_payload["item_id"]
        assert _item_field(tmp_db, item_id, "spec") == (
            "Correct the footer and verify every link."
        )
        assert _item_field(tmp_db, item_id, "workflow_posture") == (
            '{"approval_on_done": true, "path_claims": true}'
        )

    def test_payload_entry_surface_creates_a_row(
        self, tmp_db, monkeypatch,  # noqa: F811
    ):
        monkeypatch.delenv(ITEM_ENTRY_SURFACE_ENV, raising=False)
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            outcome = handle_item_create(
                _request(
                    {
                        "title": "Created via items.create",
                        "workflow": "issue",
                        "entry_surface": "harness_skill",
                    },
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
        assert _item_field(tmp_db, item_id, "workflow_id") == "issue"
        version_id = _item_field(tmp_db, item_id, "workflow_version_id")
        assert isinstance(version_id, int) and version_id > 0

    def test_missing_entry_surface_blocked_end_to_end(
        self, tmp_db, monkeypatch,  # noqa: F811
    ):
        monkeypatch.delenv(ITEM_ENTRY_SURFACE_ENV, raising=False)
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            outcome = handle_item_create(
                _request({"title": "Naive create", "workflow": "issue"}),
            )
        assert outcome.primary_success is False
        assert outcome.error.code == "entry_surface_denied"
        assert "typed entry surface" in outcome.error.message
