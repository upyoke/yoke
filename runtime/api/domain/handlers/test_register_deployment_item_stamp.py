"""Registration wiring for the internal deployment member-item stamp."""

from __future__ import annotations

import pytest

from yoke_core.domain import yoke_function_registry
from yoke_core.domain.handlers import __init_register__ as init_register
from yoke_core.domain.handlers import _register_deployment_item_stamp

_MODULE = "yoke_core.domain.handlers.deployment_item_stamp"
_FUNCTION_ID = "deployment_item_stamp.record"


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    yoke_function_registry.reset_registry_for_tests()
    yield
    yoke_function_registry.reset_registry_for_tests()


def test_deployment_item_stamp_registered() -> None:
    init_register.register_all_handlers()
    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    assert _FUNCTION_ID in ids
    assert _register_deployment_item_stamp in init_register._DOMAIN_REGISTRARS


def test_deployment_item_stamp_is_internal_session_optional() -> None:
    init_register.register_all_handlers()
    entry = yoke_function_registry.lookup(_FUNCTION_ID)
    assert entry is not None
    assert entry.adapter_status == "internal"
    assert entry.target_kinds == ("item",)
    assert entry.owner_module == _MODULE
    assert entry.claim_required_kind is None
    assert entry.ambient_session_required is False
    assert "item_deploy_stage_write" in entry.side_effects
    assert "item_deployed_to_write" in entry.side_effects
