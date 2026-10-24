"""Declared function events: the registry adds the dispatcher event and
every declared name exists in the event catalog."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from yoke_core.domain import yoke_function_registry
from yoke_core.domain.event_catalog import EVENT_CATALOG
from yoke_core.domain.handlers import __init_register__ as init_register
from yoke_core.domain.yoke_function_registry import (
    DISPATCHER_EVENT_NAME,
    RegistryValidationError,
)

# events.emit emits the caller's payload name, guarded against the catalog
# at call time, so its declaration names the payload field, not an event.
_PAYLOAD_EVENT_PLACEHOLDER = "<payload.name>"


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    yoke_function_registry.reset_registry_for_tests()
    yield
    yoke_function_registry.reset_registry_for_tests()


class _Model(BaseModel):
    pass


def _register(**overrides):
    kwargs = {
        "stability": "stable",
        "owner_module": "yoke_core.domain.test_module",
        "target_kinds": ["global"],
        "side_effects": [],
        "guardrails": [],
        "adapter_status": "live",
    }
    kwargs.update(overrides)
    return yoke_function_registry.register(
        "test.events.op", lambda _request: None, _Model, _Model, **kwargs
    )


def test_every_declared_event_exists_in_catalog() -> None:
    init_register.register_all_handlers()

    missing = sorted(
        (entry.function_id, name)
        for entry in yoke_function_registry.list_entries()
        for name in entry.emitted_event_names
        if name not in EVENT_CATALOG and name != _PAYLOAD_EVENT_PLACEHOLDER
    )
    assert missing == []


def test_every_entry_declares_dispatcher_event_first_and_once() -> None:
    init_register.register_all_handlers()

    entries = yoke_function_registry.list_entries()
    assert entries
    for entry in entries:
        assert entry.emitted_event_names[0] == DISPATCHER_EVENT_NAME
        assert entry.emitted_event_names.count(DISPATCHER_EVENT_NAME) == 1


def test_registry_prepends_dispatcher_event_to_declared_events() -> None:
    assert _register().emitted_event_names == (DISPATCHER_EVENT_NAME,)
    yoke_function_registry.reset_registry_for_tests()
    entry = _register(emitted_event_names=["WorkClaimed"])
    assert entry.emitted_event_names == (DISPATCHER_EVENT_NAME, "WorkClaimed")


def test_hand_declared_dispatcher_event_is_refused() -> None:
    with pytest.raises(RegistryValidationError, match="remove it from"):
        _register(emitted_event_names=[DISPATCHER_EVENT_NAME])
