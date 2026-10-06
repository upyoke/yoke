"""HC-packaged-hook-boundaries: installed hooks use only shipped code."""

from __future__ import annotations

from pathlib import Path
from threading import Event

from yoke_core.api.repo_root import find_repo_root
from yoke_project_checks import check_packaged_hook_boundaries as hc


def _write(root: Path, name: str, body: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_current_tree_satisfies_packaged_hook_boundaries() -> None:
    repo_root = find_repo_root(Path(__file__))
    assert hc.scan_packaged_hook_boundaries(repo_root) == []


def test_direct_source_namespace_import_is_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pkg/consumer.py",
        "from runtime.harness import hook_runner\n",
    )
    findings = hc.scan_source_namespace_edges(
        tmp_path,
        package_roots=("pkg",),
        registry_root="missing",
    )
    assert [finding.detail for finding in findings] == [
        "imports source-only module runtime.harness",
    ]


def test_registry_source_namespace_string_is_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "registry/chains.py",
        "CHAIN = ('runtime.harness.guard',)\n",
    )
    findings = hc.scan_source_namespace_edges(
        tmp_path,
        package_roots=(),
        registry_root="registry",
    )
    assert [finding.detail for finding in findings] == [
        "registry names source-only module runtime.harness.guard",
    ]


def test_thin_adapter_local_engine_import_is_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "adapter.py",
        "from yoke_core.hooks import local_entry\n",
    )
    findings = hc.scan_thin_adapter_engine_edges(
        tmp_path,
        adapter="adapter.py",
    )
    assert [finding.detail for finding in findings] == [
        "thin entrypoint imports local engine module yoke_core.hooks.local_entry",
    ]


def test_silent_local_engine_import_handler_is_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "adapter.py",
        "import importlib\n"
        "def evaluate():\n"
        "    try:\n"
        "        importlib.import_module('yoke_core.hooks.local_entry')\n"
        "    except ImportError:\n"
        "        return 0\n",
    )
    findings = hc.scan_local_engine_fail_loud(tmp_path, adapter="adapter.py")
    assert [finding.detail for finding in findings] == [
        "missing stderr report or raise",
        "missing nonzero return or raise",
        "contains a zero, empty, or non-integer return",
    ]


def test_parallel_source_analysis_preserves_order_and_ast_values(tmp_path, monkeypatch):
    _write(tmp_path, "pkg/a.py", "import ｒｕｎｔｉｍｅ.harness\n")
    _write(tmp_path, "pkg/b.py", "from runtime.harness import hook_runner\n")
    _write(tmp_path, "registry/chains.py", r"CHAIN = '\x72untime.harness.guard'" + "\n")
    original = hc._parse
    second_parsed = Event()
    completed = []

    def parse(path):
        if path.name == "a.py":
            assert second_parsed.wait(5)
        tree = original(path)
        completed.append(path.name)
        if path.name == "b.py":
            second_parsed.set()
        return tree

    monkeypatch.setattr(hc, "_parse", parse)
    findings = hc.scan_source_namespace_edges(
        tmp_path, package_roots=("pkg",), registry_root="registry"
    )
    assert completed[:2] == ["b.py", "a.py"]
    assert [(row.relpath, row.line) for row in findings] == [
        ("pkg/a.py", 1),
        ("pkg/b.py", 1),
        ("registry/chains.py", 1),
    ]
