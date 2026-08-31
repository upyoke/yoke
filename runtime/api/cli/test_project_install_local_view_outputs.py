"""Generated local views stay on disk and out of the install commit.

The ignore policy for a Yoke-installed checkout keeps generated views —
the board render, the strategy renders under ``.yoke/strategy/``, the
install manifest — untracked. The install commit therefore classifies
every manifest-owned output git ignores as a local view: written, never
staged, never force-added, and untracked when an older checkout still
carries it in the index.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_cli.project_install import checkout_gate
from yoke_core.domain.project_install_test_helpers import make_bundle, strategy_entry

STRATEGY_VIEW_REL = ".yoke/strategy/LANDSCAPE.md"


@pytest.fixture(autouse=True)
def _isolate_git_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _repo_ignoring_strategy_views(root: Path) -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "yoke@test.invalid")
    _git(root, "config", "user.name", "Yoke Test")
    (root / ".gitignore").write_text(".yoke/strategy/\n", encoding="utf-8")
    _git(root, "add", ".gitignore")
    _git(root, "commit", "-m", "ignore strategy views")
    return root


def _write_view(root: Path, body: str) -> Path:
    view = root / STRATEGY_VIEW_REL
    view.parent.mkdir(parents=True, exist_ok=True)
    view.write_text(body, encoding="utf-8")
    return view


def test_ignored_view_is_written_but_never_staged(tmp_path: Path) -> None:
    root = _repo_ignoring_strategy_views(tmp_path / "repo")
    view = _write_view(root, "# render\n")
    (root / "tracked.md").write_text("bundle output\n", encoding="utf-8")

    result = checkout_gate.commit_touched_paths(
        root,
        {
            "yoke_version": "9.9.9",
            "files_written": ["tracked.md"],
            "strategy_files_written": [STRATEGY_VIEW_REL],
        },
    )

    assert result["status"] == "created"
    assert result["paths"] == ["tracked.md"]
    assert STRATEGY_VIEW_REL in result["untracked_local_outputs"]
    assert result["untracked_from_index"] == []
    assert view.read_text(encoding="utf-8") == "# render\n"
    assert STRATEGY_VIEW_REL not in _git(root, "ls-files")
    assert "tracked.md" in _git(root, "ls-files")


def test_previously_tracked_view_is_dropped_from_the_index(tmp_path: Path) -> None:
    root = _repo_ignoring_strategy_views(tmp_path / "repo")
    _write_view(root, "# stale render\n")
    _git(root, "add", "-f", STRATEGY_VIEW_REL)
    _git(root, "commit", "-m", "view tracked before the ignore name existed")
    _write_view(root, "# fresh render\n")

    result = checkout_gate.commit_touched_paths(
        root,
        {"yoke_version": "9.9.9", "strategy_files_written": [STRATEGY_VIEW_REL]},
    )

    assert result["status"] == "created"
    assert result["untracked_from_index"] == [STRATEGY_VIEW_REL]
    assert STRATEGY_VIEW_REL not in _git(root, "ls-files")
    view_text = (root / STRATEGY_VIEW_REL).read_text(encoding="utf-8")
    assert view_text == "# fresh render\n"
    assert _git(root, "status", "--porcelain", "--untracked-files=all").strip() == ""


def test_install_manifest_is_classified_as_a_local_view(tmp_path: Path) -> None:
    root = _repo_ignoring_strategy_views(tmp_path / "repo")
    (root / ".gitignore").write_text(
        ".yoke/strategy/\n.yoke/install-manifest.json\n", encoding="utf-8",
    )
    manifest = root / ".yoke/install-manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("{}\n", encoding="utf-8")

    result = checkout_gate.commit_touched_paths(
        root, {"yoke_version": "9.9.9", "files_written": [".gitignore"]},
    )

    assert result["status"] == "created"
    assert ".yoke/install-manifest.json" in result["untracked_local_outputs"]
    assert ".yoke/install-manifest.json" not in _git(root, "ls-files")


def test_install_applies_on_a_checkout_that_ignores_strategy_views(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    from yoke_cli.project_install import runner

    bundle = make_bundle(strategy=[strategy_entry("LANDSCAPE", "# Landscape\n")])
    monkeypatch.setattr(runner, "_resolve_bundle", lambda *_a, **_k: (bundle, "test"))
    monkeypatch.setattr(
        runner, "_register_in_machine_config", lambda *_a, **_k: False,
    )
    root = _repo_ignoring_strategy_views(tmp_path / "repo")

    report = runner.install(root, project_id=7)

    assert report["strategy_files_written"] == [STRATEGY_VIEW_REL]
    assert report["commit"]["status"] == "created"
    assert STRATEGY_VIEW_REL in report["commit"]["untracked_local_outputs"]
    assert (root / STRATEGY_VIEW_REL).is_file()
    tracked = _git(root, "ls-files")
    assert STRATEGY_VIEW_REL not in tracked
    assert ".claude/skills/yoke/SKILL.md" in tracked
    assert _git(root, "status", "--porcelain", "--untracked-files=all").strip() == ""
