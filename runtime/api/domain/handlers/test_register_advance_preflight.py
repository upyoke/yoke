"""Registration wiring for the internal advance preflight gate evals.

The wiring contract: importing ``_register_advance_preflight`` in the
domain import block AND listing it in ``_DOMAIN_REGISTRARS`` must both
happen for ``register_all_handlers()`` to register the four
``advance.preflight.*`` function ids. They are internal (no CLI adapter),
item-scoped, side-effect-free reads.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import yoke_function_registry
from yoke_core.domain.handlers import __init_register__ as init_register

_PREFLIGHT_FUNCTION_IDS = (
    "advance.preflight.hard_blocks",
    "advance.preflight.ac_presence",
    "advance.preflight.file_budget",
    "advance.preflight.spec_coverage",
)


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    yoke_function_registry.reset_registry_for_tests()
    yield
    yoke_function_registry.reset_registry_for_tests()


def test_all_preflight_gate_evals_registered() -> None:
    init_register.register_all_handlers()
    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    for function_id in _PREFLIGHT_FUNCTION_IDS:
        assert function_id in ids


@pytest.mark.parametrize("function_id", _PREFLIGHT_FUNCTION_IDS)
def test_preflight_gate_eval_is_internal_item_scoped_read(function_id) -> None:
    init_register.register_all_handlers()
    entry = yoke_function_registry.lookup(function_id)
    assert entry is not None
    assert entry.adapter_status == "internal"
    assert entry.target_kinds == ("item",)
    assert entry.side_effects == ()
    assert entry.claim_required_kind is None
    assert entry.owner_module == (
        "yoke_core.domain.handlers.advance_preflight_gate_evals"
    )
