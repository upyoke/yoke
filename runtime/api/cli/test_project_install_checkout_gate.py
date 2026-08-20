"""Checkout preflight and bundle-output commit for project install/refresh."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from yoke_cli.main import main as cli_main
from yoke_cli.project_install import checkout_gate
from yoke_cli.project_install.files import ProjectInstallError
from yoke_core.domain.project_install_test_helpers import make_bundle


@pytest.fixture(autouse=True)
def _isolate_git_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _git_repo(root: Path, *, branch: str = "main") -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", branch)
    _git(root, "config", "user.email", "yoke@test.invalid")
    _git(root, "config", "user.name", "Yoke Test")
    _git(root, "commit", "--allow-empty", "-m", "init")
    return root


def test_non_git_directory_skips_the_gate(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    info = checkout_gate.assert_ready_for_write(
        root, default_branch="main",
    )
    assert info["status"] == "skipped"
    assert checkout_gate.commit_touched_paths(
        root, {"yoke_version": "9.9.9"},
    )["status"] == "skipped"


def test_dirty_tree_refuses_and_names_the_path(tmp_path: Path) -> None:
    root = _git_repo(tmp_path / "repo")
    (root / "scratch.txt").write_text("operator\n", encoding="utf-8")

    with pytest.raises(ProjectInstallError) as raised:
        checkout_gate.assert_ready_for_write(root, default_branch="main")

    message = str(raised.value)
    assert "scratch.txt" in message
    assert "--force" in message
    assert "git stash --include-untracked" in message


def test_force_accepts_a_dirty_tree(tmp_path: Path) -> None:
    root = _git_repo(tmp_path / "repo")
    (root / "scratch.txt").write_text("operator\n", encoding="utf-8")
    info = checkout_gate.assert_ready_for_write(
        root, default_branch="main", force=True,
    )
    assert info["status"] == "forced"
    assert "scratch.txt" in info["dirty_paths"]


def test_off_default_branch_refuses(tmp_path: Path) -> None:
    root = _git_repo(tmp_path / "repo", branch="main")
    _git(root, "switch", "-c", "topic")

    with pytest.raises(ProjectInstallError) as raised:
        checkout_gate.assert_ready_for_write(root, default_branch="main")

    message = str(raised.value)
    assert "topic" in message
    assert "default_branch is 'main'" in message
    assert "git switch main" in message


def test_source_apply_skips_the_default_branch_check(tmp_path: Path) -> None:
    root = _git_repo(tmp_path / "repo", branch="main")
    _git(root, "switch", "-c", "topic")
    info = checkout_gate.assert_ready_for_write(
        root, default_branch="main", require_default_branch=False,
    )
    assert info["status"] == "ok"


def test_commit_covers_untracked_and_deleted_owned_paths(tmp_path: Path) -> None:
    root = _git_repo(tmp_path / "repo")
    tracked = root / "gone.txt"
    tracked.write_text("old\n", encoding="utf-8")
    _git(root, "add", "gone.txt")
    _git(root, "commit", "-m", "track gone")
    tracked.unlink()
    (root / "fresh.txt").write_text("new\n", encoding="utf-8")
    (root / "operator.txt").write_text("leave me\n", encoding="utf-8")

    result = checkout_gate.commit_touched_paths(
        root,
        {
            "yoke_version": "9.9.9",
            "files_written": ["fresh.txt"],
            "files_pruned": ["gone.txt"],
        },
        operation="refresh",
    )

    assert result["status"] == "created"
    assert result["paths"] == ["fresh.txt", "gone.txt"]
    assert "Refresh installed Yoke operating layer to 9.9.9" in result["message"]
    names = _git(root, "ls-files").stdout.splitlines()
    assert "fresh.txt" in names
    assert "gone.txt" not in names
    assert "operator.txt" not in names
    status = _git(root, "status", "--porcelain").stdout
    assert "operator.txt" in status
    assert "fresh.txt" not in status


def test_no_commit_leaves_the_bundle_output_uncommitted(tmp_path: Path) -> None:
    root = _git_repo(tmp_path / "repo")
    (root / "fresh.txt").write_text("new\n", encoding="utf-8")
    result = checkout_gate.commit_touched_paths(
        root,
        {"yoke_version": "1", "files_written": ["fresh.txt"]},
        skip=True,
    )
    assert result["status"] == "skipped"
    assert "fresh.txt" in _git(root, "status", "--porcelain").stdout


def _seed_https(cfg: Path, tmp_path: Path) -> None:
    token = tmp_path / "api.token"
    token.write_text("test-token\n", encoding="utf-8")
    rc = cli_main([
        "connection", "set", "local",
        "--transport", "https",
        "--api-url", "http://127.0.0.1:1",
        "--token-file", str(token),
        "--config", str(cfg),
    ])
    assert rc == 0


def test_install_cli_refuses_dirty_git_checkout(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    cfg = tmp_path / "machine-home" / "config.json"
    _seed_https(cfg, tmp_path)
    capsys.readouterr()
    monkeypatch.setattr(
        "yoke_cli.project_install.runner._resolve_bundle",
        lambda *_a, **_k: (make_bundle(), "test"),
    )
    root = _git_repo(tmp_path / "repo")
    (root / "scratch.txt").write_text("operator\n", encoding="utf-8")

    rc = cli_main([
        "project", "install", str(root),
        "--project-id", "7", "--config", str(cfg), "--json",
    ])

    assert rc == 1
    err = capsys.readouterr().err
    assert "scratch.txt" in err
    assert "--force" in err
    assert not (root / ".yoke/install-manifest.json").exists()


def test_source_preview_does_not_enforce_dirty_tree(
    tmp_path: Path, capsys,
) -> None:
    target = _git_repo(tmp_path / "external")
    (target / "scratch.txt").write_text("operator\n", encoding="utf-8")
    source = Path(__file__).resolve().parents[3]

    rc = cli_main([
        "project", "refresh", str(target),
        "--source-checkout", str(source),
        "--project-id", "41", "--project-slug", "preview-project", "--json",
    ])

    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["preview"] is True
    assert report["target_writes"] is False
    assert "commit" not in report
    assert (target / "scratch.txt").read_text(encoding="utf-8") == "operator\n"


def test_install_commits_bundle_output_on_a_clean_default_branch(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    from yoke_cli.project_install import runner

    monkeypatch.setattr(
        runner, "_resolve_bundle",
        lambda *_a, **_k: (make_bundle(), "test"),
    )
    monkeypatch.setattr(
        runner, "_register_in_machine_config", lambda *_a, **_k: False,
    )
    root = _git_repo(tmp_path / "repo")
    report = runner.install(root, project_id=7)

    assert report["commit"]["status"] == "created"
    assert report["commit"]["message"].startswith("Install Yoke operating layer")
    assert _git(root, "status", "--porcelain").stdout.strip() == ""
    assert (root / ".claude/skills/yoke/SKILL.md").is_file()
