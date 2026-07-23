"""Invocation semantics of ``register_all_handlers``.

Idempotent re-runs collapse to the same registry, and a second caller
blocks until an in-flight bootstrap finishes rather than observing a
half-registered registry. Family and entry-metadata coverage lives in the
sibling ``test_handlers_init_register`` module.
"""

from __future__ import annotations

import threading

import pytest
from pydantic import BaseModel
from yoke_contracts.api.function_call import HandlerOutcome

from yoke_core.domain import yoke_function_registry
from yoke_core.domain.handlers import __init_register__ as init_register


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    yoke_function_registry.reset_registry_for_tests()
    yield
    yoke_function_registry.reset_registry_for_tests()


def test_register_all_handlers_is_idempotent() -> None:
    init_register.register_all_handlers()
    first_ids = sorted(
        entry.function_id for entry in yoke_function_registry.list_entries()
    )
    init_register.register_all_handlers()
    second_ids = sorted(
        entry.function_id for entry in yoke_function_registry.list_entries()
    )

    assert first_ids == second_ids


class _RegistrarRaceRequest(BaseModel):
    pass


class _RegistrarRaceResponse(BaseModel):
    ok: bool


def _registrar_race_handler(_request):
    return HandlerOutcome(result_payload={"ok": True}, primary_success=True)


def _registrar_race_kwargs() -> dict[str, object]:
    return {
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.test_registrar_race",
        "target_kinds": ["global"],
        "side_effects": [],
        "emitted_event_names": [],
        "guardrails": [],
        "adapter_status": "live",
    }


def test_register_all_handlers_waits_for_in_flight_bootstrap(monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()

    class SlowFirstRegistrar:
        @staticmethod
        def register(registry) -> None:
            registry.register(
                "test.first.run",
                _registrar_race_handler,
                _RegistrarRaceRequest,
                _RegistrarRaceResponse,
                **_registrar_race_kwargs(),
            )
            started.set()
            assert release.wait(timeout=2)

    class SecondRegistrar:
        @staticmethod
        def register(registry) -> None:
            registry.register(
                "test.second.run",
                _registrar_race_handler,
                _RegistrarRaceRequest,
                _RegistrarRaceResponse,
                **_registrar_race_kwargs(),
            )

    monkeypatch.setattr(
        init_register,
        "_DOMAIN_REGISTRARS",
        (SlowFirstRegistrar, SecondRegistrar),
    )

    thread = threading.Thread(target=init_register.register_all_handlers)
    thread.start()
    assert started.wait(timeout=2)
    timer = threading.Timer(0.05, release.set)
    timer.start()
    try:
        init_register.register_all_handlers()
    finally:
        release.set()
        timer.cancel()
        thread.join(timeout=2)

    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    assert {"test.first.run", "test.second.run"} <= ids
    assert not thread.is_alive()
