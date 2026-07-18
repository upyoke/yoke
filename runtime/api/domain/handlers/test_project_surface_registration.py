"""Registration coverage for project infrastructure and artifact surfaces."""

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


def test_project_artifact_handlers_registered() -> None:
    init_register.register_all_handlers()
    ids = {entry.function_id for entry in yoke_function_registry.list_entries()}
    assert "projects.artifacts.render" in ids
    assert "project.artifacts.refresh" in ids
