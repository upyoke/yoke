"""Registration wiring for the internal merge preflight gate reads.

The wiring contract: importing ``_register_merge_preflight`` in the domain
import block AND listing it in ``_DOMAIN_REGISTRARS`` must both happen for
``register_all_handlers()`` to register the three ``merge.preflight.*``
function ids. They are internal (no CLI adapter), side-effect-free reads.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import yoke_function_registry
from yoke_core.domain.handlers import __init_register__ as init_register

_MERGE_PREFLIGHT_FUNCTION_IDS = (
    "merge.preflight.epic_task_statuses",
    "merge.preflight.dependency_gate",
    "merge.preflight.blocked_gate",
)

_EXPECTED_TARGET_KINDS = {
    "merge.preflight.epic_task_statuses": ("item",),
    "merge.preflight.dependency_gate": ("item", "global"),
    "merge.preflight.blocked_gate": ("global",),
}


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    yoke_function_registry.reset_registry_for_tests()
    yield
    yoke_function_registry.reset_registry_for_tests()


def test_all_merge_preflight_reads_registered() -> None:
    init_register.register_all_handlers()
    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    for function_id in _MERGE_PREFLIGHT_FUNCTION_IDS:
        assert function_id in ids


@pytest.mark.parametrize("function_id", _MERGE_PREFLIGHT_FUNCTION_IDS)
def test_merge_preflight_read_is_internal_claim_free(function_id) -> None:
    init_register.register_all_handlers()
    entry = yoke_function_registry.lookup(function_id)
    assert entry is not None
    assert entry.adapter_status == "internal"
    assert entry.target_kinds == _EXPECTED_TARGET_KINDS[function_id]
    assert entry.side_effects == ()
    assert entry.claim_required_kind is None
    assert entry.owner_module == (
        "yoke_core.domain.handlers.merge_preflight_gate_evals"
    )
