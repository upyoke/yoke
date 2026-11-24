from types import ModuleType
from unittest.mock import MagicMock

import pytest

from runtime.stale_test_binding_guard import find_stale_test_bindings


def _connect():
    pass


@pytest.mark.parametrize(
    "source",
    [
        "runtime.api.domain.no_change_dash_close_out_test_support",
        "tests.fixtures",
        "conftest",
    ],
)
def test_reports_function_from_test_module(monkeypatch, source):
    module = ModuleType("yoke_core.delivery_member_close_effects")
    monkeypatch.setattr(_connect, "__module__", source)
    module.connect = _connect

    assert find_stale_test_bindings(set(), {module.__name__: module}) == [
        (module.__name__, "connect", source),
    ]


def test_reports_fake_class_instance_and_mock():
    module = ModuleType("yoke_cli.config.onboard_build_report")
    source = "runtime.api.cli.setup_agent_test_support"
    fake_apply = type("FakeApply", (), {"__module__": source})
    module.fake_class = fake_apply
    module.apply_with_durable_report = fake_apply()
    module.preview = MagicMock()

    assert find_stale_test_bindings(set(), {module.__name__: module}) == [
        (module.__name__, "apply_with_durable_report", source),
        (module.__name__, "fake_class", source),
        (module.__name__, "preview", "unittest.mock"),
    ]


def test_ignores_product_objects_builtins_and_module_values(monkeypatch):
    module = ModuleType("yoke_core.example")
    monkeypatch.setattr(_connect, "__module__", module.__name__)
    module.connect = _connect
    module.client = type("Client", (), {"__module__": module.__name__})()
    module.length = len
    module.support = ModuleType("runtime.api.support")
    module.__getattr__ = len

    assert find_stale_test_bindings(set(), {module.__name__: module}) == []


def test_ignores_already_imported_and_non_product_modules():
    already_imported = ModuleType("yoke_core.already_imported")
    helper = ModuleType("runtime.api.helper")
    product = ModuleType("yoke_contracts.newly_imported")
    modules = {
        module.__name__: module for module in (already_imported, helper, product)
    }
    for module in modules.values():
        module.fake = MagicMock()
    modules["yoke_core.missing"] = None

    assert find_stale_test_bindings({already_imported.__name__}, modules) == [
        (product.__name__, "fake", "unittest.mock"),
    ]
