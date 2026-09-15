"""Registration wiring for the internal done-transition control-plane reads.

The wiring contract: importing ``_register_done_transition`` in the domain
import block AND listing it in ``_DOMAIN_REGISTRARS`` must both happen for
``register_all_handlers()`` to register the ``done_transition.*`` function
ids. They are internal (no CLI adapter), and all but the owner delivery
notice are side-effect-free reads — that one sends a message, and declares
it.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import yoke_function_registry
from yoke_core.domain.handlers import __init_register__ as init_register

_ITEM_MODULE = "yoke_core.domain.handlers.done_transition_item_reads"
_DEPLOY_MODULE = "yoke_core.domain.handlers.done_transition_deploy_reads"
_NOTICE_MODULE = "yoke_core.domain.handlers.done_transition_delivery_notice"

# function_id -> (target_kinds, owner_module)
_DONE_TRANSITION_READS = {
    "done_transition.item_context": (("item",), _ITEM_MODULE),
    "done_transition.item_field": (("item",), _ITEM_MODULE),
    "done_transition.blocked_gate": (("item",), _ITEM_MODULE),
    "done_transition.epic_task_list": (("global",), _ITEM_MODULE),
    "done_transition.epic_task_github_issues": (("global",), _ITEM_MODULE),
    "done_transition.registered_flow_ids": (("global",), _DEPLOY_MODULE),
    "done_transition.latest_deployment_run": (("item",), _DEPLOY_MODULE),
    "done_transition.run_stage": (("global",), _DEPLOY_MODULE),
    "done_transition.run_blocking_qa": (("global",), _DEPLOY_MODULE),
    "done_transition.run_stage_qa_acceptance": (("item",), _DEPLOY_MODULE),
    "done_transition.done_preconditions": (("item",), _DEPLOY_MODULE),
}


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    yoke_function_registry.reset_registry_for_tests()
    yield
    yoke_function_registry.reset_registry_for_tests()


def test_all_done_transition_reads_registered() -> None:
    init_register.register_all_handlers()
    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    for function_id in _DONE_TRANSITION_READS:
        assert function_id in ids
    assert "done_transition.delivery_done_notice" in ids


def test_delivery_notice_declares_the_message_it_sends() -> None:
    """The one done-transition function that writes says so."""
    init_register.register_all_handlers()
    entry = yoke_function_registry.lookup("done_transition.delivery_done_notice")
    assert entry is not None
    assert entry.adapter_status == "internal"
    assert entry.target_kinds == ("item",)
    assert entry.side_effects == ("session_message",)
    assert entry.claim_required_kind is None
    assert entry.owner_module == _NOTICE_MODULE


@pytest.mark.parametrize("function_id", sorted(_DONE_TRANSITION_READS))
def test_done_transition_read_is_internal_claim_free(function_id) -> None:
    init_register.register_all_handlers()
    entry = yoke_function_registry.lookup(function_id)
    assert entry is not None
    target_kinds, owner_module = _DONE_TRANSITION_READS[function_id]
    assert entry.adapter_status == "internal"
    assert entry.target_kinds == target_kinds
    assert entry.side_effects == ()
    assert entry.claim_required_kind is None
    assert entry.owner_module == owner_module
