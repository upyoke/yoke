"""Tests for Atlas currency trigger derivation and quiet pre-commit refresh."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from yoke_core.tools import atlas_currency_inputs as inputs
from yoke_core.tools import atlas_pre_commit_refresh as refresh


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        if (parent / "docs" / "atlas.md").is_file():
            return parent
    raise RuntimeError("could not locate repo root with docs/atlas.md")


class TestCurrencyTriggerPaths:
    def test_includes_collector_surfaces(self) -> None:
        root = _repo_root()
        paths = inputs.currency_trigger_paths(root)
        assert any(
            p.endswith("operation_inventory.py") for p in paths
        ), paths
        assert any(
            p.endswith("handlers/__init_register__.py") for p in paths
        ), paths
        assert any(
            "commands/registry.py" in p for p in paths
        ), paths
        assert any(
            "yoke_function_registry.py" in p for p in paths
        ), paths

    def test_includes_registry_and_inventory_siblings(self) -> None:
        root = _repo_root()
        paths = inputs.currency_trigger_paths(root)
        assert any(
            p.endswith("registry_workflows.py") for p in paths
        ), paths
        assert any(
            p.endswith("operation_inventory_data.py") for p in paths
        ), paths

    def test_unrelated_path_does_not_touch(self) -> None:
        root = _repo_root()
        assert inputs.staged_touches_currency_inputs(
            root, ["README.md", "docs/testing-verification.md"],
        ) is False

    def test_inventory_path_touches(self) -> None:
        root = _repo_root()
        paths = inputs.currency_trigger_paths(root)
        sample = next(
            p for p in paths if p.endswith("operation_inventory.py")
        )
        assert inputs.staged_touches_currency_inputs(root, [sample]) is True


class TestRefreshIfStale:
    def test_unrelated_staged_is_silent_noop(
        self, tmp_path: Path, monkeypatch, capsys,
    ) -> None:
        monkeypatch.setattr(
            refresh, "build_report", lambda _root: (_ for _ in ()).throw(
                AssertionError("build_report must not run"),
            ),
        )
        result = refresh.refresh_if_stale(
            tmp_path, staged_paths=["README.md"],
        )
        assert result is None
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_current_atlas_is_silent_noop(
        self, tmp_path: Path, monkeypatch, capsys,
    ) -> None:
        report = {"generated_at": "1970-01-01T00:00:00Z"}
        body = "# atlas\n"
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "atlas.md").write_text(body, encoding="utf-8")
        monkeypatch.setattr(refresh, "build_report", lambda _root: report)
        monkeypatch.setattr(refresh, "render", lambda _report: body)
        monkeypatch.setattr(
            refresh, "staged_touches_currency_inputs",
            lambda _root, _paths: True,
        )
        result = refresh.refresh_if_stale(
            tmp_path,
            staged_paths=[
                "packages/yoke-cli/src/yoke_cli/operation_inventory.py",
            ],
        )
        assert result is None
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_stale_atlas_is_written(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        report = {"generated_at": "1970-01-01T00:00:00Z"}
        body = "# refreshed atlas\n"
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "atlas.md").write_text("# stale\n", encoding="utf-8")
        monkeypatch.setattr(refresh, "build_report", lambda _root: report)
        monkeypatch.setattr(refresh, "render", lambda _report: body)
        monkeypatch.setattr(
            refresh, "staged_touches_currency_inputs",
            lambda _root, _paths: True,
        )
        written = refresh.refresh_if_stale(
            tmp_path, staged_paths=["x"],
        )
        assert written == tmp_path / "docs" / "atlas.md"
        assert written.read_text(encoding="utf-8") == body

    def test_stale_then_write_is_green(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        report = {"generated_at": "1970-01-01T00:00:00Z"}
        body = "# refreshed atlas\n"
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "atlas.md").write_text("# stale\n", encoding="utf-8")
        monkeypatch.setattr(refresh, "build_report", lambda _root: report)
        monkeypatch.setattr(refresh, "render", lambda _report: body)
        monkeypatch.setattr(
            refresh, "staged_touches_currency_inputs",
            lambda _root, _paths: True,
        )
        assert refresh.refresh_if_stale(tmp_path, staged_paths=["x"]) is not None
        assert refresh.refresh_if_stale(tmp_path, staged_paths=["x"]) is None

    def test_stage_atlas_runs_git_add(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        written_path = tmp_path / "docs" / "atlas.md"
        written_path.parent.mkdir()
        written_path.write_text("# x\n", encoding="utf-8")
        monkeypatch.setattr(
            refresh, "refresh_if_stale",
            lambda root, *, staged_paths=None: written_path,
        )
        calls: list[list[str]] = []

        def fake_run(argv, **kwargs):
            calls.append(list(argv))
            return mock.Mock(returncode=0)

        monkeypatch.setattr(refresh.subprocess, "run", fake_run)
        result = refresh.stage_atlas_if_refreshed(
            tmp_path, staged_paths=["x"],
        )
        assert result == written_path
        assert calls
        assert calls[0][:3] == ["git", "-C", str(tmp_path.resolve())]
        assert "docs/atlas.md" in calls[0]


class TestHarnessPreCommitHook:
    def test_run_invokes_atlas_refresh(self, monkeypatch) -> None:
        from yoke_harness.git_hooks import pre_commit as gate

        called: list[bool] = []

        def fake_refresh() -> None:
            called.append(True)

        monkeypatch.setattr(
            gate, "_refresh_atlas_currency_or_skip", fake_refresh,
        )
        monkeypatch.setattr(gate, "_emit_diverged_warning", lambda: None)
        monkeypatch.setattr(gate, "_run_file_line_check_or_block", lambda: 0)
        assert gate.run() == 0
        assert called == [True]

    def test_missing_yoke_core_skips_quietly(self, monkeypatch, capsys) -> None:
        from yoke_harness.git_hooks import pre_commit as gate

        monkeypatch.setattr(
            gate, "_resolve_repo_root", lambda: str(_repo_root()),
        )

        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("yoke_core.tools"):
                raise ImportError("simulated missing yoke_core")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        gate._refresh_atlas_currency_or_skip()
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
