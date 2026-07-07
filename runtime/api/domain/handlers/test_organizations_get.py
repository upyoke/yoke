"""Handler coverage for ``organizations.get`` (disposable Postgres)."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import organizations_get as org_handler


def _request(payload=None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="organizations.get",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


class TestOrganizationsGet:
    def test_default_reads_identity_card(self, test_db):
        outcome = org_handler.handle_organizations_get(_request())
        assert outcome.primary_success
        assert outcome.result_payload["slug"] == "default"
        assert outcome.result_payload["name"] == "Default Org"
        assert outcome.result_payload["created_at"]

    def test_rename_reads_back(self, test_db):
        from yoke_core.domain import org_schema

        org_schema.rename_org(test_db, "default", "Universe Under Test")
        outcome = org_handler.handle_organizations_get(_request())
        assert outcome.primary_success
        assert outcome.result_payload["name"] == "Universe Under Test"

    def test_slug_addresses_specific_org(self, test_db):
        test_db.execute(
            "INSERT INTO organizations (slug, name, created_at) "
            "VALUES (%s, %s, %s)",
            ("second", "Second Org", "2026-02-02T00:00:00Z"),
        )
        test_db.commit()
        outcome = org_handler.handle_organizations_get(
            _request({"slug": "second"})
        )
        assert outcome.primary_success
        assert outcome.result_payload == {
            "slug": "second",
            "name": "Second Org",
            "created_at": "2026-02-02T00:00:00Z",
        }

    def test_unknown_slug_not_found(self, test_db):
        outcome = org_handler.handle_organizations_get(
            _request({"slug": "nope"})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "not_found"

    def test_non_string_slug_rejected(self, test_db):
        outcome = org_handler.handle_organizations_get(
            _request({"slug": ["not", "a", "string"]})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"


class TestRegistration:
    def test_registered_as_claimless_read(self):
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain.yoke_function_actor_identity import is_read_only
        from yoke_core.domain.yoke_function_registry import lookup

        register_all_handlers()
        entry = lookup("organizations.get")
        assert entry is not None
        assert not entry.side_effects
        assert entry.claim_required_kind is None
        assert is_read_only(entry)

    def test_authz_scope_is_actor_session(self):
        from yoke_core.domain.function_authz_scope import (
            ACTOR_SESSION,
            classify,
        )

        spec = classify(
            "organizations.get", side_effects=False, project_permission=None,
        )
        assert spec.scope == ACTOR_SESSION
