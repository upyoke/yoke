"""The per-OS known-failure baselines name real tests, each with a reason."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime import known_failure_baseline as baseline

REPO_ROOT = Path(__file__).resolve().parents[1]
SUITE_ROOTS = ("runtime/api/", "runtime/harness/", "tests/")


def _defined_tests(path: Path) -> set[str]:
    """``name`` and ``Class::name`` for every test function the module defines."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    names = {node.name for node in tree.body if isinstance(node, functions)}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            names |= {
                f"{node.name}::{child.name}"
                for child in node.body
                if isinstance(child, functions)
            }
    return names


def _entry_problem(node_id: str, reason: object) -> str | None:
    if not isinstance(reason, str) or not reason.strip():
        return "has no reason"
    if "\\" in node_id:
        return "must use / separators"
    file_part, separator, test_part = node_id.partition("::")
    if not separator or not file_part.startswith(SUITE_ROOTS):
        return "is not a suite node id (path.py::test)"
    path = REPO_ROOT / file_part
    if not path.is_file():
        return f"names missing file {file_part}"
    test = test_part.split("[", 1)[0]
    if test not in _defined_tests(path):
        return f"names no test {test} in {file_part}"
    return None


@pytest.mark.parametrize("os_name", sorted(set(baseline.PLATFORM_BASELINES.values())))
def test_every_entry_names_a_real_test_with_a_reason(os_name: str) -> None:
    entries = baseline.load_baseline(os_name)
    problems = {
        node_id: problem
        for node_id, reason in entries.items()
        if (problem := _entry_problem(node_id, reason)) is not None
    }
    assert problems == {}, baseline.baseline_path(os_name)


def test_entry_check_rejects_missing_reason_file_and_test() -> None:
    real = "tests/test_known_failure_baseline.py::test_entry_check_rejects_missing_reason_file_and_test"
    assert _entry_problem(real, "why") is None
    assert _entry_problem(real + "[case]", "why") is None
    assert _entry_problem(real, " ") == "has no reason"
    assert "missing file" in _entry_problem("tests/test_absent.py::test_x", "why")
    assert "names no test" in _entry_problem("tests/test_known_failure_baseline.py::test_absent", "why")
    assert "separators" in _entry_problem("tests\\test_known_failure_baseline.py::test_x", "why")


class _Item(SimpleNamespace):
    def add_marker(self, marker) -> None:
        self.markers.append(marker)


def _marked(monkeypatch, platform: str, enabled: bool, entries: dict[str, str]):
    monkeypatch.setattr(baseline.sys, "platform", platform)
    if enabled:
        monkeypatch.setenv(baseline.ENABLE_ENV, "1")
    else:
        monkeypatch.delenv(baseline.ENABLE_ENV, raising=False)
    monkeypatch.setattr(baseline, "load_baseline", lambda _os: entries)
    items = [
        _Item(nodeid=node_id, markers=[])
        for node_id in ("tests/a.py::test_x[1]", "tests/a.py::test_y", "tests/a.py::test_z")
    ]
    baseline.pytest_collection_modifyitems(None, items)
    return {item.nodeid: item.markers for item in items}


def test_listed_tests_become_strict_xfail_on_their_os(monkeypatch) -> None:
    marked = _marked(
        monkeypatch, "win32", True,
        {"tests/a.py::test_x": "uses fcntl", "tests/a.py::test_y": "POSIX paths"},
    )
    assert marked["tests/a.py::test_z"] == []
    for node_id, reason in (("tests/a.py::test_x[1]", "uses fcntl"), ("tests/a.py::test_y", "POSIX paths")):
        (marker,) = marked[node_id]
        assert marker.name == "xfail"
        assert marker.kwargs == {"strict": True, "reason": f"windows known failure: {reason}"}


@pytest.mark.parametrize("platform, enabled", [("linux", True), ("darwin", False)])
def test_no_baseline_applies_off_os_or_without_opt_in(monkeypatch, platform, enabled) -> None:
    marked = _marked(monkeypatch, platform, enabled, {"tests/a.py::test_y": "why"})
    assert all(markers == [] for markers in marked.values())
