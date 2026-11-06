"""Shared plugins cannot change fixture ownership with collection order."""

from __future__ import annotations

import ast
from pathlib import Path

from yoke_core.tools._impacted_fixture_graph import (
    _fixture_decorator,
    _plugin_modules,
)


def _declares_plugins(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        targets = (
            node.targets if isinstance(node, ast.Assign)
            else [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        if any(isinstance(t, ast.Name) and t.id == "pytest_plugins" for t in targets):
            return True
    return False


def _plugin_contract_errors(root: Path) -> list[str]:
    """Read source without importing helpers or collecting their tests."""
    sources = {
        path.relative_to(root).as_posix(): path.read_text()
        for directory in (root / "runtime", root / "tests")
        for path in sorted(directory.rglob("*.py"))
    }
    trees = {
        path: ast.parse(source, filename=path)
        for path, source in sources.items()
        if "pytest_plugins" in source
    }
    errors = []
    pending = []
    for path, tree in trees.items():
        if Path(path).name == "conftest.py":
            pending.extend(_plugin_modules(tree))
        elif _declares_plugins(tree):
            errors.append(
                f"{path}: pytest_plugins is session-global; import fixtures explicitly"
            )
    seen = set()
    owners = {}
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        path = module.replace(".", "/") + ".py"
        source = sources.get(path)
        if source is None:
            continue  # External plugins do not belong to this repository contract.
        tree = ast.parse(source, filename=path)
        pending.extend(_plugin_modules(tree))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                fixture = _fixture_decorator(decorator)
                if fixture is None:
                    continue
                name = fixture[1] or node.name
                previous = owners.setdefault(name, path)
                if previous != path:
                    errors.append(
                        f"fixture {name!r} is defined by registered plugins "
                        f"{previous} and {path}; import it explicitly in its consumers"
                    )
    return sorted(errors)


def test_repository_fixture_plugins_have_unambiguous_ownership():
    root = Path(__file__).resolve().parents[3]
    assert not (errors := _plugin_contract_errors(root)), "\n".join(errors)


def _write(root: Path, path: str, source: str) -> None:
    destination = root / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source)


def test_contract_refuses_test_module_plugin_even_without_fixtures(tmp_path):
    _write(tmp_path, "runtime/test_example.py", "pytest_plugins = []\n")
    errors = _plugin_contract_errors(tmp_path)
    assert len(errors) == 1
    assert "runtime/test_example.py" in errors[0]
    assert "import fixtures explicitly" in errors[0]


def test_contract_refuses_plugin_declaration_in_non_test_helper(tmp_path):
    _write(tmp_path, "tests/helper.py", "pytest_plugins: tuple = ('tests.plugin',)\n")
    assert "tests/helper.py" in _plugin_contract_errors(tmp_path)[0]


def test_contract_names_both_plugins_for_duplicate_fixture(tmp_path):
    _write(
        tmp_path, "runtime/conftest.py",
        "pytest_plugins = ('runtime.first', 'runtime.second')\n",
    )
    _write(
        tmp_path, "runtime/first.py",
        "import pytest\n@pytest.fixture\ndef conn(): pass\n",
    )
    _write(
        tmp_path, "runtime/second.py",
        "import pytest\n@pytest.fixture(name='conn', autouse=True)\ndef other(): pass\n",
    )
    errors = _plugin_contract_errors(tmp_path)
    assert len(errors) == 1
    assert "'conn'" in errors[0]
    assert "runtime/first.py" in errors[0]
    assert "runtime/second.py" in errors[0]


def test_contract_allows_directory_override_and_repeated_registration(tmp_path):
    _write(
        tmp_path, "runtime/conftest.py",
        "pytest_plugins = ['runtime.plugin', 'runtime.plugin']\n",
    )
    _write(
        tmp_path, "runtime/plugin.py",
        "import pytest\n@pytest.fixture()\ndef conn(): pass\n",
    )
    _write(
        tmp_path, "runtime/nested/conftest.py",
        "import pytest\n@pytest.fixture\ndef conn(): pass\n",
    )
    assert _plugin_contract_errors(tmp_path) == []
