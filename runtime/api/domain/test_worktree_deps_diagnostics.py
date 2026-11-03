"""Dependency installation skip output must explain the files and recovery."""

import pytest

from yoke_core.domain import worktree_deps


@pytest.fixture(autouse=True)
def isolate_install(monkeypatch):
    monkeypatch.setattr(worktree_deps, "resolve_playwright_cache", lambda *args: None)
    monkeypatch.setattr(worktree_deps, "_get_setup_command", lambda *args: None)
    monkeypatch.setattr(worktree_deps.runtime_settings, "get_seconds", lambda *args: 600)
    monkeypatch.setattr(worktree_deps.shutil, "which", lambda name: None)


@pytest.mark.parametrize(
    ("filename", "installer"),
    [("package-lock.json", "npm"), ("yarn.lock", "yarn"),
     ("pnpm-lock.yaml", "pnpm"), ("requirements.txt", "pip")],
)
def test_missing_nested_installer_names_file_and_recovery(tmp_path, capsys, filename, installer):
    nested = tmp_path / "app"
    nested.mkdir()
    (nested / filename).write_text("")

    assert worktree_deps.install_worktree_deps(str(tmp_path), "42") == 0

    output = capsys.readouterr().err
    assert f"app/{filename}" in output
    assert f"{installer} not on PATH" in output
    assert "No dependency files detected" not in output
    assert "yoke projects capability-settings set --project 42" in output
    assert "--cap-type setup_command" in output
    assert '--settings-json \'{"command":"<documented environment command>"}\' --new' in output
    assert "Declare setup_command once at project level" in output
    assert "documented environment command (its lockfile or toolchain script)" in output
    assert "requires project authority" in output
    assert "ask steering or the operator" in output
    assert "Lane prepare runs it automatically; do not hand-prepare each lane" in output
    assert "Rerun lane prepare" in output
    assert "pip install" not in output


def test_bare_pyproject_explains_missing_uv_and_lockfile(tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')

    assert worktree_deps.install_worktree_deps(str(tmp_path), "42") == 0

    output = capsys.readouterr().err
    assert "Skipping pyproject.toml" in output
    assert "uv not on PATH" in output
    assert "requires uv.lock" in output
    assert "--cap-type setup_command" in output
    assert "No dependency files detected" not in output


def test_empty_tree_teaches_setup_command(tmp_path, capsys):
    assert worktree_deps.install_worktree_deps(str(tmp_path)) == 0

    output = capsys.readouterr().err
    assert "No dependency files detected — skipping install" in output
    assert "--project <project> --cap-type setup_command" in output


def test_uv_owned_tree_does_not_claim_files_are_absent(tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    (tmp_path / "uv.lock").write_text("version = 1\n")

    assert worktree_deps.install_worktree_deps(str(tmp_path)) == 0

    output = capsys.readouterr().err
    assert "uv-managed" in output
    assert "pyproject.toml" in output
    assert "No dependency files detected" not in output
    assert "requires uv.lock" not in output
