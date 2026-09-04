"""Registration wiring for the done-transition and landing-marker writes.

The wiring contract: importing ``_register_done_transition_writes`` in the
domain import block AND listing it in ``_DOMAIN_REGISTRARS`` must both
happen for ``register_all_handlers()`` to register the write function ids.
They are internal (no CLI adapter), session-optional (the done transition
runs in a merge subprocess that may resolve no ambient session), and
claim-free (the inline writes they replace were claim-free), but — unlike
the read siblings — they declare side effects.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import yoke_function_registry
from yoke_core.domain.handlers import __init_register__ as init_register

_MODULE = "yoke_core.domain.handlers.done_transition_writes"
_MARKER_MODULE = "yoke_core.domain.handlers.merge_queue_marker_writes"
_OBSERVE_MODULE = "yoke_core.domain.handlers.merge_queue_landing_observe"

# function_id -> (expected side_effects, owning module)
_DONE_TRANSITION_WRITES = {
    "done_transition.finalize_local_side_effects": (
        ("item_deployed_to_write", "release_entry_write"),
        _MODULE,
    ),
    "done_transition.populate_merged_at": (("item_merged_at_write",), _MODULE),
    "merge_queue.landing_pull_request.record": (
        ("item_merge_queue_marker_write",),
        _MARKER_MODULE,
    ),
    "merge_queue.landing_pending.mark": (
        ("item_merge_queue_marker_write",),
        _MARKER_MODULE,
    ),
    "merge_queue.landing_pending.clear": (
        ("item_merge_queue_marker_write",),
        _MARKER_MODULE,
    ),
    "merge_queue.landing.observe": (
        (
            "github_merge_queue_read",
            "item_merge_queue_observation_write",
            "session_message_write",
        ),
        _OBSERVE_MODULE,
    ),
}


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    yoke_function_registry.reset_registry_for_tests()
    yield
    yoke_function_registry.reset_registry_for_tests()


def test_all_done_transition_writes_registered() -> None:
    init_register.register_all_handlers()
    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    for function_id in _DONE_TRANSITION_WRITES:
        assert function_id in ids


@pytest.mark.parametrize("function_id", sorted(_DONE_TRANSITION_WRITES))
def test_done_transition_write_is_internal_session_optional(function_id) -> None:
    init_register.register_all_handlers()
    entry = yoke_function_registry.lookup(function_id)
    assert entry is not None
    side_effects, owner_module = _DONE_TRANSITION_WRITES[function_id]
    assert entry.adapter_status == "internal"
    assert entry.target_kinds == ("item",)
    assert entry.owner_module == owner_module
    # A write is not read-only, so it would be denied for a missing session
    # unless ambient_session_required is False — the merge subprocess posture.
    assert entry.side_effects == side_effects
    assert entry.claim_required_kind is None
    assert entry.ambient_session_required is False
