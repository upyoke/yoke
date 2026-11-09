"""The installed service registrar remains safe through the domain port."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from yoke_core.domain import yoke_function_registry as registry
from yoke_core.domain.handler_registry_runtime import ensure_handlers_registered


@pytest.fixture(autouse=True)
def empty_registry():
    registry.reset_registry_for_tests()
    yield
    registry.reset_registry_for_tests()


def test_installed_runtime_registers_catalog_and_recovers_after_reset():
    ensure_handlers_registered()
    expected = {entry.function_id for entry in registry.list_entries()}
    assert "projects.capability.has" in expected
    assert "workflow_item.epic_task.body_replace" in expected

    registry.reset_registry_for_tests()
    ensure_handlers_registered()
    assert {entry.function_id for entry in registry.list_entries()} == expected


def test_concurrent_domain_bootstrap_installs_one_complete_catalog():
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: _catalog(), range(8)))
    assert results[0]
    assert all(result == results[0] for result in results)


def _catalog():
    ensure_handlers_registered()
    return {entry.function_id for entry in registry.list_entries()}


def test_port_preserves_a_deliberately_supplied_catalog(monkeypatch):
    from yoke_core.api import handler_registry_runtime as runtime
    from yoke_core.domain.handlers import __init_register__ as registrar

    # The registrar's populated-registry guard protects injected test catalogs.
    monkeypatch.setattr(registry, "list_entries", lambda: [object()])
    monkeypatch.setattr(registrar, "_REGISTRATION_COMPLETE", False)
    runtime.ensure_handlers_registered()
    assert not registrar._REGISTRATION_COMPLETE
