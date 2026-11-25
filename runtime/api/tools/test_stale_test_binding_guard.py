import sys
from functools import partial
from importlib import import_module
from pathlib import Path
from types import MethodType, ModuleType
from unittest.mock import MagicMock

import pytest

from runtime import stale_test_binding_guard
from runtime.stale_test_binding_guard import find_stale_test_bindings


_REPO_ROOT = Path(__file__).resolve().parents[3]


def _source_module(name, relative_path):
    module = ModuleType(name)
    module.__file__ = str(_REPO_ROOT / relative_path)
    return module


def _connect():
    pass


@pytest.mark.parametrize(
    ("source", "path"),
    [
        (
            "runtime.api.domain.no_change_dash_close_out_test_support",
            "runtime/api/domain/no_change_dash_close_out_test_support.py",
        ),
        ("tests.fixtures", "tests/fixtures.py"),
        ("conftest", "conftest.py"),
        ("test_unpacked", "runtime/api/hooks/test_unpacked.py"),
    ],
)
def test_reports_function_from_test_module(monkeypatch, source, path):
    module = ModuleType("yoke_core.delivery_member_close_effects")
    monkeypatch.setattr(_connect, "__module__", source)
    module.connect = _connect

    modules = {module.__name__: module, source: _source_module(source, path)}
    assert find_stale_test_bindings({}, modules) == [
        (module.__name__, "connect", source),
    ]


def test_reports_fake_class_instance_and_mock():
    module = ModuleType("yoke_cli.config.onboard_build_report")
    source = "runtime.api.cli.setup_agent_test_support"
    fake_apply = type("FakeApply", (), {"__module__": source})
    module.fake_class = fake_apply
    module.apply_with_durable_report = fake_apply()
    module.preview = MagicMock()

    modules = {
        module.__name__: module,
        source: _source_module(source, "runtime/api/cli/setup_agent_test_support.py"),
    }
    assert find_stale_test_bindings({}, modules) == [
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
    external = _source_module("runtime.external", "/opt/third-party/runtime/external.py")
    module.external = type("External", (), {"__module__": external.__name__})()

    assert find_stale_test_bindings(
        {}, {module.__name__: module, external.__name__: external}
    ) == []


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

    assert find_stale_test_bindings(
        {already_imported.__name__: id(already_imported)}, modules
    ) == [
        (product.__name__, "fake", "unittest.mock"),
    ]


def test_reports_bound_methods_and_partials(monkeypatch):
    module = ModuleType("yoke_core.example")
    helper = _source_module("test_unpacked", "tests/installer/test_unpacked.py")

    class FakeConnection:
        def connect(self):
            pass

    monkeypatch.setattr(FakeConnection.connect, "__module__", helper.__name__)
    module.connect = FakeConnection().connect
    module.method_from_partial = MethodType(partial(FakeConnection.connect), FakeConnection())
    module.partial_connect = partial(module.connect)

    assert find_stale_test_bindings(
        {}, {module.__name__: module, helper.__name__: helper}
    ) == [
        (module.__name__, "connect", helper.__name__),
        (module.__name__, "method_from_partial", helper.__name__),
        (module.__name__, "partial_connect", helper.__name__),
    ]


def test_reports_module_reimported_under_the_same_name():
    original = ModuleType("yoke_cli.example")
    reimported = ModuleType(original.__name__)
    reimported.apply = MagicMock()

    assert find_stale_test_bindings(
        {original.__name__: id(original)}, {reimported.__name__: reimported}
    ) == [
        (reimported.__name__, "apply", "unittest.mock"),
    ]


def test_pre_import_binds_alias_before_source_is_patched(tmp_path, monkeypatch):
    package = tmp_path / "yoke_binding_probe"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "source.py").write_text("operation = len\n", encoding="utf-8")
    (package / "consumer.py").write_text(
        "from .source import operation\n", encoding="utf-8"
    )
    source_name = f"{package.name}.source"
    consumer_name = f"{package.name}.consumer"
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(stale_test_binding_guard, "_PRODUCT_PACKAGES", (package.name,))
    try:
        stale_test_binding_guard.pytest_configure()
        before = {name: id(module) for name, module in sys.modules.copy().items()}
        with monkeypatch.context() as patch:
            patch.setattr(import_module(source_name), "operation", MagicMock())
            consumer = import_module(consumer_name)
        assert consumer.operation is len
        assert find_stale_test_bindings(before, sys.modules.copy()) == []
    finally:
        for name in (consumer_name, source_name, package.name):
            sys.modules.pop(name, None)
