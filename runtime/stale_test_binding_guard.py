"""Fail the test that leaves a test double in a newly imported product module."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from functools import partial
from pathlib import Path
from types import FunctionType, MethodType, ModuleType
from unittest.mock import NonCallableMock

import pytest


_MODULES_BEFORE = pytest.StashKey[dict[str, int]]()
_REPO_ROOT = Path(__file__).resolve().parents[1]
_TEST_ROOTS = (_REPO_ROOT / "runtime", _REPO_ROOT / "tests")


def _is_test_code(module: ModuleType | None) -> bool:
    path = vars(module).get("__file__") if module is not None else None
    if not isinstance(path, str):
        return False
    resolved = Path(path).resolve()
    return resolved.name == "conftest.py" or any(
        resolved.is_relative_to(root) for root in _TEST_ROOTS
    )


def find_stale_test_bindings(
    modules_before: Mapping[str, int],
    modules: Mapping[str, ModuleType | None],
) -> list[tuple[str, str, str]]:
    """Return (product module, attribute, defining module) for each leaked fake."""
    hits = []
    test_code: dict[str, bool] = {}
    for name, module in modules.items():
        if not name.startswith("yoke_"):
            continue
        if module is None or id(module) == modules_before.get(name):
            continue
        for attribute, value in vars(module).copy().items():
            while issubclass(type(value), partial):
                value = value.func
            if type(value) is MethodType:
                value = value.__func__
            value_type = type(value)
            if issubclass(value_type, ModuleType):
                continue
            if value_type is FunctionType or issubclass(value_type, type):
                defining_module = value.__module__
            else:
                defining_module = value_type.__module__
            if not isinstance(defining_module, str):
                continue
            if defining_module not in test_code:
                test_code[defining_module] = _is_test_code(modules.get(defining_module))
            if issubclass(value_type, NonCallableMock) or test_code[defining_module]:
                hits.append((name, attribute, defining_module))
    return sorted(hits)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_setup(item: pytest.Item):
    item.stash[_MODULES_BEFORE] = {
        name: id(module) for name, module in sys.modules.copy().items()
        if name.startswith("yoke_")
    }
    return (yield)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_teardown(item: pytest.Item):
    try:
        return (yield)
    finally:
        modules_before = item.stash.get(_MODULES_BEFORE, None)
        if modules_before is not None:
            del item.stash[_MODULES_BEFORE]
            hits = find_stale_test_bindings(modules_before, sys.modules.copy())
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
