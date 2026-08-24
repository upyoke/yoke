"""Coverage for the registered changed-path Ruff command."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.tools import ruff_changed


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _repo_with_baseline(tmp_path: Path, files: dict[str, str]) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Yoke Test")
    _git(repo, "config", "user.email", "test@example.com")
    for relative, content in files.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_changed_paths_exclude_deleted_python_files(tmp_path: Path) -> None:
    repo, base = _repo_with_baseline(
        tmp_path,
        {"deleted.py": "gone = True\n", "kept.py": "value = 1\n"},
    )
    (repo / "deleted.py").unlink()
    (repo / "kept.py").write_text("value = 2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "change and delete")

    assert ruff_changed.changed_python_paths(base, repo) == ("kept.py",)


def test_changed_paths_use_the_rename_destination(tmp_path: Path) -> None:
    repo, base = _repo_with_baseline(tmp_path, {"old.py": "value = 1\n"})
    (repo / "nested").mkdir()
    _git(repo, "mv", "old.py", "nested/renamed.py")
    _git(repo, "commit", "-m", "rename")

    assert ruff_changed.changed_python_paths(base, repo) == ("nested/renamed.py",)


def test_empty_changed_set_passes_without_invoking_ruff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, base = _repo_with_baseline(tmp_path, {"module.py": "value = 1\n"})
    invoked = False

    def _unexpected(*_args, **_kwargs) -> int:
        nonlocal invoked
        invoked = True
        return 1

    monkeypatch.setattr(ruff_changed, "_run_ruff", _unexpected)

    assert ruff_changed.run(base, root=repo) == 0
    assert invoked is False
    assert "no changed Python files" in capsys.readouterr().out


def test_format_check_runs_after_lint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        ruff_changed,
        "changed_python_paths",
        lambda _base, _root: ("module.py",),
    )
    phases: list[tuple[str, ...]] = []

    def _record(
        _root: Path,
        arguments: tuple[str, ...],
        _paths: tuple[str, ...],
    ) -> int:
        phases.append(arguments)
        return 0

    monkeypatch.setattr(ruff_changed, "_run_ruff", _record)

    assert ruff_changed.run("main", format_check=True, root=tmp_path) == 0
    assert phases == [("check",), ("format", "--check")]


def test_cli_adapter_uses_the_claimed_source_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yoke_cli.commands.adapters import source_dev_run as adapter

    captured: list[str] = []

    def _run(command: list[str]) -> int:
        captured.extend(command)
        return 7

    monkeypatch.setattr(
        adapter.importlib,
        "import_module",
        lambda name: (
            SimpleNamespace(run=_run)
            if name == "yoke_core.tools.source_dev_run"
            else None
        ),
    )

    assert adapter.ruff_changed(["--base", "main", "--format-check"]) == 7
    assert captured == [
        "python3",
        "-m",
        "yoke_core.tools.ruff_changed",
        "--base",
        "main",
        "--format-check",
    ]


def test_command_is_registered_as_a_local_tool() -> None:
    from yoke_cli import operation_inventory
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY
    from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS

    assert ("dev", "ruff-changed") not in SUBCOMMAND_REGISTRY
    assert ("dev", "ruff-changed") in TOOL_SHAPED_SUBCOMMANDS
    entry = operation_inventory.lookup("yoke dev ruff-changed")
    assert entry is not None
    assert entry.status == operation_inventory.TOOL_CLI
    assert entry.family == "tools.ruff_changed"
