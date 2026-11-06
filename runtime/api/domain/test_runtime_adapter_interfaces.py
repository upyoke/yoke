"""Runtime interface composition and the core domain dependency boundary."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol

import pytest

from yoke_contracts import runtime_ports
from yoke_contracts.runtime_ports import loader


class Operation(Protocol):
    run: object


@pytest.fixture(autouse=True)
def isolate_port_cache():
    loader.load_port.cache_clear()
    yield
    loader.load_port.cache_clear()


def entry(name, implementation):
    return SimpleNamespace(name=name, load=lambda: implementation)


def test_interface_accepts_an_independent_implementation(monkeypatch):
    implementation = SimpleNamespace(run=lambda value: value + 1)
    monkeypatch.setattr(
        loader, "_installed_ports", lambda: (entry("operation", implementation),)
    )
    port = loader.load_port("operation", Operation)
    assert port.run(3) == 4
    assert loader.load_port("operation", Operation) is port


@pytest.mark.parametrize("count", [0, 2])
def test_interface_refuses_missing_or_ambiguous_installation(monkeypatch, count):
    monkeypatch.setattr(
        loader,
        "_installed_ports",
        lambda: tuple(entry("operation", SimpleNamespace(run=object())) for _ in range(count)),
    )
    with pytest.raises(loader.RuntimeAdapterUnavailable) as caught:
        loader.load_port("operation", Operation)
    assert "runtime_adapter_unavailable: operation" in str(caught.value)
    assert f"found {count}" in str(caught.value)
    assert "official installer" in str(caught.value)


def test_interface_refuses_an_incomplete_implementation(monkeypatch):
    monkeypatch.setattr(
        loader, "_installed_ports", lambda: (entry("operation", SimpleNamespace()),)
    )
    with pytest.raises(loader.RuntimeAdapterUnavailable, match="missing run"):
        loader.load_port("operation", Operation)


def test_interface_names_an_unloadable_implementation(monkeypatch):
    def unavailable():
        raise ImportError("implementation dependency unavailable")

    monkeypatch.setattr(
        loader,
        "_installed_ports",
        lambda: (SimpleNamespace(name="operation", load=unavailable),),
    )
    with pytest.raises(loader.RuntimeAdapterUnavailable, match="could not load.*ImportError"):
        loader.load_port("operation", Operation)


def test_domain_has_no_adapter_package_imports():
    root = Path(__file__).resolve().parents[3]
    domain = root / "packages/yoke-core/src/yoke_core/domain"
    violations = []
    for path in domain.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            for module in modules:
                if module.split(".")[0] in {"yoke_cli", "yoke_harness"}:
                    violations.append(f"{path.name}:{node.lineno}: {module}")
    assert violations == []


def test_installed_adapters_satisfy_the_published_interfaces():
    directory = Path(runtime_ports.__file__).parent
    for path in sorted(directory.glob("*.py")):
        if path.stem in {"__init__", "loader"}:
            continue
        module = importlib.import_module(f"yoke_contracts.runtime_ports.{path.stem}")
        implementation = getattr(module, f"get_{path.stem}")()
        assert implementation is not None
