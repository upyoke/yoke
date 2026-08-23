"""Registry metadata for the semantic migration-content verifier."""

from yoke_contracts.migration_content_identity import FUNCTION_ID
from yoke_core.domain.handlers import __init_register__ as init_register
from yoke_core.domain.handlers import _register_migration_content_identity
from yoke_core.domain import yoke_function_registry


def test_registered_verifier_is_a_global_read_with_a_live_adapter() -> None:
    yoke_function_registry.reset_registry_for_tests()
    try:
        init_register.register_all_handlers()
        entry = yoke_function_registry.lookup(FUNCTION_ID)

        assert entry is not None
        assert entry.target_kinds == ("global",)
        assert entry.side_effects == ()
        assert entry.adapter_status == "live"
        assert entry.ambient_session_required is False
        assert "ledger_digest_redaction" in entry.guardrails
        assert _register_migration_content_identity in init_register._DOMAIN_REGISTRARS
    finally:
        yoke_function_registry.reset_registry_for_tests()
