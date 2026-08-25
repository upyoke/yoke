"""Checkout-shaped pytest argv, source binding, and empty-roots selection."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from yoke_core.domain.qa_environment_declaration import TestEnvironmentDeclaration
from yoke_core.domain.verification_tree_binding import ClaimLookup
from yoke_core.tools import _source_pythonpath, watch_pytest_project_python as helper


def test_yoke_shaped_tree_uses_the_current_interpreter(
    tmp_path: Path, monkeypatch
) -> None:
    marker = tmp_path / "packages" / "yoke-core" / "src" / "yoke_core"
    marker.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    argv = helper.pytest_argv(["runtime/api/"], cwd=tmp_path)
    assert argv[:3] == [sys.executable, "-m", "pytest"]


def test_non_uv_tree_keeps_the_current_interpreter(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    monkeypatch.setattr(
        helper,
        "load_declaration",
        lambda **_k: TestEnvironmentDeclaration(project="other"),
    )
    argv = helper.pytest_argv(["pkgx"], cwd=tmp_path)
    assert argv[:3] == [sys.executable, "-m", "pytest"]


def test_declared_extras_on_a_uv_project_use_uv_run(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        helper,
        "load_declaration",
        lambda **_k: TestEnvironmentDeclaration(
            project="platform", extras=("engine",)
        ),
    )
    argv = helper.pytest_argv(["tests/"], cwd=tmp_path)
    assert argv[:6] == [
        "uv",
        "run",
        "--frozen",
        "--extra",
        "engine",
        "python3",
    ]


def test_source_entries_bind_only_on_a_yoke_shaped_tree(tmp_path: Path) -> None:
    base = {"PYTHONPATH": "/already/there"}
    external = _source_pythonpath.with_source_pythonpath(base, tmp_path)
    assert external["PYTHONPATH"] == "/already/there"

    (tmp_path / "packages" / "yoke-core" / "src" / "yoke_core").mkdir(parents=True)
    bound = _source_pythonpath.with_source_pythonpath(base, tmp_path)
    assert bound["PYTHONPATH"].split(os.pathsep)[0] == str(
        (tmp_path / _source_pythonpath.PACKAGE_SRC_RELS[0]).resolve()
    )


def test_empty_roots_print_the_named_verdict(capsys, monkeypatch) -> None:
    monkeypatch.setattr(helper, "resolve_test_roots", lambda _root: ())
    assert helper.impacted_selection("main") is None
    assert "unsupported_project_test_roots" in capsys.readouterr().out


def test_impacted_tree_prefers_the_unique_claimed_sibling(
    tmp_path: Path,
    monkeypatch,
) -> None:
    main = tmp_path / "repo"
    lane = tmp_path / "lane"
    main.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=main, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=main, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=main, check=True)
    (main / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    subprocess.run(["git", "add", "pyproject.toml"], cwd=main, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=main, check=True)
    subprocess.run(
        ["git", "worktree", "add", "-b", "item", str(lane)],
        cwd=main,
        check=True,
    )
    monkeypatch.setattr(
        "yoke_core.domain.verification_tree_binding.ambient_session_id",
        lambda: "session-1",
    )
    monkeypatch.setattr(
        "yoke_core.domain.verification_tree_binding.resolve_claim_worktrees",
        lambda _session: ClaimLookup(worktrees=(str(lane),)),
    )

    assert helper.impacted_tree(main) == lane

    changed_test = "runtime/api/test_new_untracked.py"
    trigger = "notes/new-untracked.txt"
    (lane / changed_test).parent.mkdir(parents=True)
    (lane / changed_test).write_text(
        "def test_new():\n    assert True\n", encoding="utf-8"
    )
    (lane / trigger).parent.mkdir(parents=True)
    (lane / trigger).write_text("new\n", encoding="utf-8")
    from yoke_core.tools import _impacted_import_index, _impacted_selection

    def test_roots() -> tuple[str, ...]:
        return ("runtime/api/",)

    monkeypatch.setattr(_impacted_import_index, "current_test_roots", test_roots)
    monkeypatch.setattr(_impacted_selection, "current_test_roots", test_roots)
    monkeypatch.setattr(helper, "resolve_test_roots", lambda _root: test_roots())

    selection = helper.impacted_selection(
        "main",
        bounded=True,
        root=lane,
    )

    assert selection is not None and selection.bounded_deferral is True
    assert selection.fallback_rule == "unmapped_file_kind"
    assert selection.trigger_paths == (trigger,)
    assert changed_test in selection.files
