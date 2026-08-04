"""Focused tests for Python event-emitter discovery shapes."""

from yoke_core.domain.events_registry_discovery import (
    _discover_python_event_names,
)


def test_dispatcher_emit_payload_literal_is_discovered() -> None:
    source = """
call_dispatcher(
    function_id="events.emit",
    payload={"name": "DirectDispatcherEvent", "severity": "INFO"},
)
"""

    assert _discover_python_event_names(source) == ["DirectDispatcherEvent"]


def test_dispatcher_emit_payload_event_name_constant_is_discovered() -> None:
    source = """
RECEIPT_EVENT_NAME = "ConstantDispatcherEvent"
call_dispatcher(
    function_id="events.emit",
    payload={"name": RECEIPT_EVENT_NAME},
)
"""

    assert _discover_python_event_names(source) == ["ConstantDispatcherEvent"]


def test_non_emission_dispatcher_call_is_ignored() -> None:
    source = """
call_dispatcher(
    function_id="events.query.run",
    payload={"name": "NotAnEmission"},
)
"""

    assert _discover_python_event_names(source) == []


def test_positional_severity_is_not_treated_as_an_event_name() -> None:
    source = """
def _emit_lease_event(name, severity, lease):
    pass

_emit_lease_event(LEASE_EVENT, "INFO", object())
"""

    assert _discover_python_event_names(source) == []
