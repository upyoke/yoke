"""Tests for ``yoke_core.tools.search_code``.

Covers AC-1 through AC-9: scope routing, default excludes, engine selection
(rg + Python fallback), multi-worktree handling, and failure cases.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple

import pytest

from yoke_core.tools import search_code


def _seed_tree(root: Path) -> None:
    """Populate *root* with a small mixed tree exercising excludes + binary."""
    (root / "src").mkdir(parents=True)
    (root / "src" / "alpha.py").write_text(
        "def needle():\n    return 'haystack'\n", encoding="utf-8",
    )
    (root / "src" / "beta.py").write_text(
        "haystack_lower\nNEEDLE = True\n", encoding="utf-8",
    )
    for excluded in search_code.DEFAULT_EXCLUDES:
        d = root / excluded
        d.mkdir()
        (d / "buried.py").write_text("needle\n", encoding="utf-8")
    (root / "image.bin").write_bytes(b"\x00needle\x00binary")


def _resolved(
    paths: Tuple[str, ...],
    repo: str,
    *,
    scope: str = "item",
) -> search_code.ResolvedWorktree:
    return search_code.ResolvedWorktree(
        path=paths[0] if paths else "",
        branch="YOK-9999",
        repo=repo,
        project="yoke",
        exists=all(Path(p).is_dir() for p in paths) if paths else False,
        scope=scope,
        paths=paths,
        branches=("YOK-9999",) * len(paths),
    )


@pytest.fixture
def fake_worktree(tmp_path):
    """Return a populated (worktree, main repo) pair."""
    repo = tmp_path / "main_repo"
    repo.mkdir()
    _seed_tree(repo)
    wt = tmp_path / ".worktrees" / "YOK-9999"
    _seed_tree(wt)
    return wt, repo


@pytest.fixture
def patch_resolver(monkeypatch):
    """Replace ``resolve_item_worktree`` so tests do not need a live DB."""
    def _apply(resolved: search_code.ResolvedWorktree) -> None:
        monkeypatch.setattr(
            search_code, "resolve_item_worktree", lambda _ref: resolved,
        )
    return _apply


def _run(*argv: str) -> int:
    return search_code.main(list(argv))


class TestScopeRouting:
    def test_worktree_scope_searches_only_worktree(
        self, fake_worktree, patch_resolver, capsys,
    ):
        wt, repo = fake_worktree
        (repo / "src" / "main_only.py").write_text(
            "main_only_marker\n", encoding="utf-8",
        )
        patch_resolver(_resolved((str(wt),), str(repo)))
        rc = _run("--item", "YOK-9999", "--pattern", "main_only_marker",
                  "--scope", "worktree", "--engine", "python")
        captured = capsys.readouterr()
        assert rc == search_code.EXIT_NO_MATCH, captured.out

    def test_main_scope_searches_repo_root(
        self, fake_worktree, patch_resolver, capsys,
    ):
        wt, repo = fake_worktree
        (repo / "src" / "main_only.py").write_text(
            "main_only_marker\n", encoding="utf-8",
        )
        patch_resolver(_resolved((str(wt),), str(repo)))
        rc = _run("--item", "YOK-9999", "--pattern", "main_only_marker",
                  "--scope", "main", "--engine", "python")
        captured = capsys.readouterr()
        assert rc == search_code.EXIT_OK
        assert "main_only_marker" in captured.out

    def test_worktree_scope_with_no_bound_directory_fails_with_remediation(
        self, tmp_path, patch_resolver, capsys,
    ):
        repo = tmp_path / "repo"
        repo.mkdir()
        nonexistent = tmp_path / ".worktrees" / "YOK-9999"
        patch_resolver(_resolved((str(nonexistent),), str(repo)))
        rc = _run("--item", "YOK-9999", "--pattern", "anything",
                  "--scope", "worktree", "--engine", "python")
        captured = capsys.readouterr()
        assert rc == search_code.EXIT_NO_WORKTREE
        assert "no worktree directory exists" in captured.err
        assert "worktree_preflight" in captured.err
        assert "/yoke advance" in captured.err


class TestDefaultExcludes:
    def test_python_engine_skips_every_default_exclude(
        self, fake_worktree, patch_resolver, capsys,
    ):
        wt, repo = fake_worktree
        patch_resolver(_resolved((str(wt),), str(repo)))
        rc = _run("--item", "YOK-9999", "--pattern", "needle",
                  "--scope", "worktree", "--engine", "python")
        captured = capsys.readouterr()
        assert rc == search_code.EXIT_OK
        for excluded in search_code.DEFAULT_EXCLUDES:
            assert excluded not in captured.out, (
                f"matches inside {excluded} leaked into output"
            )
        assert os.path.join("src", "alpha.py") in captured.out


class TestEngineSelection:
    def test_auto_prefers_rg_when_available(self, monkeypatch):
        monkeypatch.setattr(
            search_code.shutil, "which", lambda _x: "/usr/local/bin/rg",
        )
        assert search_code._select_engine("auto") == "rg"

    def test_auto_falls_back_when_rg_missing(self, monkeypatch):
        monkeypatch.setattr(search_code.shutil, "which", lambda _x: None)
        assert search_code._select_engine("auto") == "python"

    def test_explicit_python_forces_python(self, monkeypatch):
        monkeypatch.setattr(
            search_code.shutil, "which", lambda _x: "/usr/local/bin/rg",
        )
        assert search_code._select_engine("python") == "python"

    def test_explicit_rg_falls_back_when_missing(self, monkeypatch):
        monkeypatch.setattr(search_code.shutil, "which", lambda _x: None)
        assert search_code._select_engine("rg") == "python"


class TestPythonFallbackShape:
    def test_rg_shape_path_line_match(
        self, fake_worktree, patch_resolver, capsys,
    ):
        wt, repo = fake_worktree
        patch_resolver(_resolved((str(wt),), str(repo)))
        rc = _run("--item", "YOK-9999", "--pattern", "needle",
                  "--scope", "worktree", "--engine", "python")
        captured = capsys.readouterr()
        assert rc == search_code.EXIT_OK
        lines = [line for line in captured.out.splitlines() if line]
        # Each line is `<rel-path>:<line>:<content>`. Confirm src/alpha.py:1
        # appears in shape.
        rel_alpha = os.path.join("src", "alpha.py")
        assert any(
            line.split(":", 2)[0].endswith(rel_alpha)
            and line.split(":", 2)[1] == "1"
            for line in lines
        ), f"expected shape; got {lines!r}"

    def test_skips_binary_files(self, fake_worktree, patch_resolver, capsys):
        wt, repo = fake_worktree
        patch_resolver(_resolved((str(wt),), str(repo)))
        rc = _run("--item", "YOK-9999", "--pattern", "needle",
                  "--scope", "worktree", "--engine", "python")
        captured = capsys.readouterr()
        assert rc == search_code.EXIT_OK
        assert "image.bin" not in captured.out


def _have_rg() -> bool:
    return search_code.shutil.which("rg") is not None


@pytest.mark.skipif(not _have_rg(), reason="rg not installed")
class TestRgEngine:
    def test_rg_engine_emits_path_line_match(
        self, fake_worktree, patch_resolver, capsys,
    ):
        wt, repo = fake_worktree
        patch_resolver(_resolved((str(wt),), str(repo)))
        rc = _run("--item", "YOK-9999", "--pattern", "needle",
                  "--scope", "worktree", "--engine", "rg")
        captured = capsys.readouterr()
        assert rc == search_code.EXIT_OK
        lines = [line for line in captured.out.splitlines() if line]
        assert lines, "rg should produce at least one match"
        for line in lines:
            assert line.count(":") >= 2, f"unexpected rg shape: {line!r}"
        for excluded in search_code.DEFAULT_EXCLUDES:
            assert excluded not in captured.out, (
                f"rg surfaced excluded dir {excluded}"
            )


class TestMultiWorktree:
    def test_multi_worktree_prefixes_each_match(
        self, tmp_path, patch_resolver, capsys,
    ):
        repo = tmp_path / "repo"
        repo.mkdir()
        wt_a = tmp_path / ".worktrees" / "YOK-1234-task-1"
        wt_b = tmp_path / ".worktrees" / "YOK-1234-task-2"
        for wt in (wt_a, wt_b):
            wt.mkdir(parents=True)
            (wt / "shared.py").write_text("needle\n", encoding="utf-8")
        patch_resolver(_resolved(
            (str(wt_a), str(wt_b)), str(repo), scope="epic-tasks",
        ))
        rc = _run("--item", "YOK-1234", "--pattern", "needle",
                  "--scope", "worktree", "--engine", "python")
        captured = capsys.readouterr()
        assert rc == search_code.EXIT_OK
        assert f"{wt_a}::shared.py:1:needle" in captured.out
        assert f"{wt_b}::shared.py:1:needle" in captured.out

    def test_multi_worktree_drops_missing_worktrees(
        self, tmp_path, patch_resolver, capsys,
    ):
        repo = tmp_path / "repo"
        repo.mkdir()
        wt_existing = tmp_path / ".worktrees" / "YOK-1234-task-1"
        wt_existing.mkdir(parents=True)
        (wt_existing / "shared.py").write_text("needle\n", encoding="utf-8")
        wt_missing = tmp_path / ".worktrees" / "YOK-1234-task-2"
        # do not create wt_missing
        patch_resolver(_resolved(
            (str(wt_existing), str(wt_missing)),
            str(repo),
            scope="epic-tasks",
        ))
        rc = _run("--item", "YOK-1234", "--pattern", "needle",
                  "--scope", "worktree", "--engine", "python")
        captured = capsys.readouterr()
        assert rc == search_code.EXIT_OK
        assert str(wt_existing) in captured.out
        assert str(wt_missing) not in captured.out


class TestFailureCases:
    def test_invalid_item_id_returns_bad_input(self, monkeypatch, capsys):
        monkeypatch.setattr(
            search_code,
            "resolve_item_worktree",
            lambda _ref: (_ for _ in ()).throw(ValueError("invalid item ID")),
        )
        rc = _run("--item", "YOK-XYZ", "--pattern", "x", "--scope", "worktree")
        captured = capsys.readouterr()
        assert rc == search_code.EXIT_BAD_INPUT
        assert "ERROR" in captured.err

    def test_unknown_item_returns_bad_input(self, monkeypatch, capsys):
        monkeypatch.setattr(
            search_code,
            "resolve_item_worktree",
            lambda _ref: (_ for _ in ()).throw(LookupError("not found")),
        )
        rc = _run("--item", "YOK-99999", "--pattern", "x", "--scope", "worktree")
        captured = capsys.readouterr()
        assert rc == search_code.EXIT_BAD_INPUT
        assert "not found" in captured.err

    def test_invalid_scope_value_rejected_by_argparse(self, capsys):
        with pytest.raises(SystemExit) as exc:
            _run("--item", "YOK-9999", "--pattern", "x", "--scope", "bogus")
        assert exc.value.code != 0
        captured = capsys.readouterr()
        assert "invalid choice" in captured.err

    def test_missing_required_flags_rejected_by_argparse(self):
        with pytest.raises(SystemExit) as exc:
            _run("--item", "YOK-9999")
        assert exc.value.code != 0

    def test_invalid_regex_returns_bad_input_for_python(
        self, fake_worktree, patch_resolver, capsys,
    ):
        wt, repo = fake_worktree
        patch_resolver(_resolved((str(wt),), str(repo)))
        rc = _run("--item", "YOK-9999", "--pattern", "[",
                  "--scope", "worktree", "--engine", "python")
        captured = capsys.readouterr()
        assert rc == search_code.EXIT_BAD_INPUT
        assert "invalid regex" in captured.err

    def test_rg_engine_error_returns_bad_input(
        self, fake_worktree, patch_resolver, monkeypatch, capsys,
    ):
        proc = type(
            "Proc", (), {"returncode": 2, "stdout": "", "stderr": "regex parse error"},
        )()
        wt, repo = fake_worktree
        patch_resolver(_resolved((str(wt),), str(repo)))
        monkeypatch.setattr(search_code.shutil, "which", lambda _x: "rg")
        monkeypatch.setattr(search_code.subprocess, "run", lambda *a, **k: proc)
        rc = _run("--item", "YOK-9999", "--pattern", "[",
                  "--scope", "worktree", "--engine", "rg")
        captured = capsys.readouterr()
        assert rc == search_code.EXIT_BAD_INPUT
        assert "regex parse error" in captured.err
