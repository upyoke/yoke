"""Fail the test that leaves a test double in a newly imported product module."""

from __future__ import annotations

import sys
from collections.abc import Mapping, Set
from types import FunctionType, ModuleType
from unittest.mock import NonCallableMock

import pytest


_MODULES_BEFORE = pytest.StashKey[set[str]]()


def find_stale_test_bindings(
    modules_before: Set[str],
    modules: Mapping[str, ModuleType | None],
) -> list[tuple[str, str, str]]:
    """Return (product module, attribute, defining module) for each leaked fake."""
    hits = []
    for name in sorted(modules.keys() - modules_before):
        if not name.startswith("yoke_"):
            continue
        module = modules[name]
        if module is None:
            continue
        for attribute, value in sorted(vars(module).items()):
            value_type = type(value)
            if issubclass(value_type, ModuleType):
                continue
            if value_type is FunctionType or issubclass(value_type, type):
                defining_module = value.__module__
            else:
                defining_module = value_type.__module__
            if issubclass(value_type, NonCallableMock) or (
                isinstance(defining_module, str)
                and (
                    defining_module == "conftest"
                    or defining_module.startswith(("runtime.", "tests."))
                )
            ):
                hits.append((name, attribute, defining_module))
    return hits


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_setup(item: pytest.Item):
    item.stash[_MODULES_BEFORE] = set(sys.modules)
    return (yield)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_teardown(item: pytest.Item):
    try:
        return (yield)
    finally:
        modules_before = item.stash.get(_MODULES_BEFORE, None)
        if modules_before is not None:
            del item.stash[_MODULES_BEFORE]
            hits = find_stale_test_bindings(modules_before, sys.modules)
            if hits:
                bindings = "\n".join(
                    f"  {module}.{attribute} is bound to an object from {source}"
                    for module, attribute, source in hits
                )
                pytest.fail(
                    f"{item.nodeid} left stale test bindings after teardown\n"
                    f"{bindings}\nResolve the patched dependency at call time.",
                    pytrace=False,
                )
