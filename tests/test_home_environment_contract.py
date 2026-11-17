"""Tests move every native home resolver together, even on POSIX runners."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


def home_environment_violations(source: str) -> list[int]:
    """Find bare HOME overrides without inspecting subprocess environments."""
    if "setenv" not in source and "clear=" not in source:
        return []
    violations = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr == "setenv" and node.args:
            if isinstance(node.args[0], ast.Constant) and node.args[0].value == "HOME":
                violations.append(node.lineno)
        if node.func.attr != "dict" or len(node.args) < 2:
            continue
        target = ast.unparse(node.args[0])
        if target not in ("os.environ", "'os.environ'"):
            continue
        if not any(
            k.arg == "clear"
            and not (isinstance(k.value, ast.Constant) and k.value.value is False)
            for k in node.keywords
        ):
            continue
        values = node.args[1]
        if isinstance(values, ast.Dict):
            keys = {k.value for k in values.keys if isinstance(k, ast.Constant)}
            names = {n.id for n in ast.walk(values) if isinstance(n, ast.Name)}
            if (
                "HOME" in keys
                and "USERPROFILE" not in keys
                and "HOME_ENVS" not in names
            ):
                violations.append(node.lineno)
    return violations


@pytest.mark.parametrize(
    "source",
    [
        'monkeypatch.setenv("HOME", str(tmp_path))',
        'mock.patch.dict(os.environ, {"HOME": "/tmp/home"}, clear=True)',
        'patch.dict("os.environ", {"HOME": home}, clear=True)',
    ],
)
def test_guard_refuses_a_planted_home_only_override(source):
    assert home_environment_violations(source) == [1]


@pytest.mark.parametrize(
    "source",
    [
        "set_home(monkeypatch, tmp_path)",
        "mock.patch.dict(os.environ, {name: home for name in HOME_ENVS}, clear=True)",
        'subprocess.run(argv, env={"HOME": home})',
        'mock.patch.dict(os.environ, {"HOME": home}, clear=False)',
    ],
)
def test_guard_accepts_portable_overrides_and_subprocess_envs(source):
    assert home_environment_violations(source) == []


def test_test_code_moves_every_home_resolver():
    root = Path(__file__).resolve().parents[1]
    violations = []
    for folder in ("tests", "runtime", "packages"):
        for path in (root / folder).rglob("*.py"):
            if "test" not in path.name and path.name != "conftest.py":
                continue
            violations.extend(
                f"{path.relative_to(root)}:{line}"
                for line in home_environment_violations(
                    path.read_text(encoding="utf-8")
                )
            )
    assert not violations, "Use set_home(monkeypatch, path):\n" + "\n".join(violations)
