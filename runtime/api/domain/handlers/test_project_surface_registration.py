"""Registration coverage for project infrastructure and Pack surfaces."""

from __future__ import annotations

import pytest

from yoke_core.domain import yoke_function_registry
from yoke_core.domain.handlers import __init_register__ as init_register


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    yoke_function_registry.reset_registry_for_tests()
    yield
    yoke_function_registry.reset_registry_for_tests()


def test_projects_infrastructure_list_handler_registered() -> None:
    init_register.register_all_handlers()
    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    assert "projects.infrastructure.list" in ids


def test_pack_handlers_are_registered() -> None:
    init_register.register_all_handlers()
    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    assert {
        "packs.list",
        "packs.bundle.get",
        "packs.project.report",
        "packs.get.run",
        "packs.relink.run",
        "packs.update.run",
    } <= ids
