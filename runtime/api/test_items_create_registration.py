"""The item-create function registers its project permission and target shape."""

from runtime.api.test_items_create_function import _FUNCTION_ID


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
