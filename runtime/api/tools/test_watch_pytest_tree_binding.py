"""Tree-binding wiring for the pytest entry points.

Both entry points refuse a run rooted outside the calling session's
claimed worktree, and both accept ``--allow-tree-mismatch`` for a
deliberate cross-tree run. The decision itself lives in
:mod:`yoke_core.domain.verification_tree_binding` and is covered by
``runtime/api/domain/test_verification_tree_binding.py``; these tests
assert the wrappers consult it, honour its verdict, and rank it against
their other pre-flight rejections.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest

from yoke_core.domain import verification_tree_binding
from yoke_core.domain.verification_tree_binding import TreeBindingVerdict
from yoke_core.tools import run_tests, watch_pytest
from yoke_core.tools._impacted_selection import Selection

REFUSAL = "REFUSAL: cd to the claimed worktree"
NOTICE = "NOTICE: running the other tree"


def _bind(module, monkeypatch: pytest.MonkeyPatch, **verdict) -> None:
    """Pin what the tree binding tells *module* about this run."""
    monkeypatch.setattr(
        module.verification_tree_binding,
        "evaluate_run",
        lambda **kwargs: TreeBindingVerdict(**verdict),
    )


def _refuse(monkeypatch: pytest.MonkeyPatch) -> None:
    _bind(watch_pytest, monkeypatch, refusal=REFUSAL)


class TestWatchPytestBinding:
    """``watch_pytest.main`` returns ``3`` and prints the refusal."""

    def test_main_exits_3_when_binding_refuses(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
    ) -> None:
        _refuse(monkeypatch)
        assert watch_pytest.main(["--", "runtime/api/", "-q"]) == 3
        captured = capsys.readouterr()
        assert REFUSAL in captured.err
        # Printed before pytest is invoked: nothing reached stdout.
        assert captured.out == ""

    def test_allow_flag_runs_and_prints_the_notice(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        _bind(watch_pytest, monkeypatch, notice=NOTICE)
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        from yoke_core.tools import _pytest_parallel

        monkeypatch.setattr(
            _pytest_parallel, "_read_free_ram_mb", lambda: 1_000_000,
        )
        rc = watch_pytest.main(
            [
                "--print-streaming-pair",
                verification_tree_binding.ALLOW_TREE_MISMATCH_FLAG,
                "--",
                "runtime/api/",
            ],
        )
        assert rc == 0
        assert NOTICE in capsys.readouterr().err

    def test_allow_flag_is_position_tolerant(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        # ``passthrough`` is a REMAINDER list, so a flag after ``--``
        # would otherwise reach pytest verbatim and fail collection.
        _bind(watch_pytest, monkeypatch, notice=NOTICE)
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        from yoke_core.tools import _pytest_parallel

        monkeypatch.setattr(
            _pytest_parallel, "_read_free_ram_mb", lambda: 1_000_000,
        )
        rc = watch_pytest.main(
            [
                "--print-streaming-pair",
                "--",
                "runtime/api/",
                verification_tree_binding.ALLOW_TREE_MISMATCH_FLAG,
            ],
        )
        assert rc == 0
        assert NOTICE in capsys.readouterr().err

    def test_main_passes_through_on_a_clean_verdict(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        _bind(watch_pytest, monkeypatch)
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        from yoke_core.tools import _pytest_parallel

        monkeypatch.setattr(
            _pytest_parallel, "_read_free_ram_mb", lambda: 1_000_000,
        )
        rc = watch_pytest.main(
            ["--print-streaming-pair", "--", "runtime/api/", "-q"],
        )
        assert rc == 0

    def test_impacted_main_call_runs_untracked_lane_selection_in_one_tree(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        main = tmp_path / "repo"
        lane = main / ".worktrees" / "foreign-lane"
        selected = "runtime/api/tools/test_new_untracked.py"
        trigger = "notes/new-untracked.txt"
        (lane / selected).parent.mkdir(parents=True)
        (lane / selected).write_text(
            "def test_new():\n    assert True\n", encoding="utf-8"
        )
        (lane / trigger).parent.mkdir(parents=True)
        (lane / trigger).write_text("new\n", encoding="utf-8")
        (main / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        (lane / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        monkeypatch.chdir(main)
        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
        monkeypatch.setattr(watch_pytest, "_impacted_tree", lambda: lane)
        selection = Selection(
            full_sweep=False,
            reason="selection unbounded (unmapped_file_kind)",
            files=(selected,),
            fallback_rule="unmapped_file_kind",
            trigger_paths=(trigger,),
            bounded_deferral=True,
        )

        def _selection(base, *, bounded=False, root=None):
            assert base == "main" and bounded is True
            assert root == lane
            return selection

        observed = {}
        monkeypatch.setattr(watch_pytest, "_impacted_selection", _selection)
        monkeypatch.setattr(
            watch_pytest.verification_tree_binding,
            "evaluate_run",
            lambda **kwargs: (
                observed.update(binding=kwargs)
                or watch_pytest.verification_tree_binding.TreeBindingVerdict()
            ),
        )
        monkeypatch.setattr(
            watch_pytest,
            "_pytest_argv",
            lambda args, *, cwd=None: (
                observed.update(argv_cwd=cwd) or ["pytest", *args]
            ),
        )
        monkeypatch.setattr(
            watch_pytest.gate_admission,
            "admitted_gate",
            lambda *_args, **_kwargs: contextlib.nullcontext(),
        )
        monkeypatch.setattr(
            watch_pytest._watch_runner,
            "run_watcher",
            lambda **kwargs: observed.update(runner=kwargs) or 0,
        )
        monkeypatch.setattr(
            watch_pytest._watch_pytest_wall_clock,
            "report",
            lambda *_args, **_kwargs: None,
        )

        assert watch_pytest.main(["--impacted", "main"]) == 0

        assert observed["binding"]["tree"] == str(lane)
        assert observed["argv_cwd"] == lane
        assert observed["runner"]["cwd"] == str(lane)
        assert selected in observed["runner"]["argv"]
        output = capsys.readouterr().out
        assert "unmapped_file_kind" in output
        assert trigger in output

    def test_nested_pytest_rejection_still_wins(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
    ) -> None:
        # Callers that grep for the nested-pytest message keep working:
        # argument-shape rejections rank ahead of the binding check.
        _refuse(monkeypatch)
        rc = watch_pytest.main(
            ["--", "python3", "-m", "pytest", "runtime/api/", "-q"],
        )
        assert rc == 2
        captured = capsys.readouterr()
        assert "bare pytest args" in captured.err
        assert REFUSAL not in captured.err


class TestRunTestsBinding:
    """``run_tests.run`` refuses before pytest is launched."""

    def test_run_refuses_and_never_launches_pytest(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        launched: list[object] = []
        _bind(run_tests, monkeypatch, refusal=REFUSAL)
        monkeypatch.setattr(
            run_tests.process_group_reaping,
            "popen_in_process_group",
            lambda *args, **kwargs: launched.append(args),
        )
        rc = run_tests.run(["tests"], repo_root=tmp_path)
        assert rc == run_tests._EXIT_STATUS_TREE_BINDING_REFUSED
        assert launched == []
        assert REFUSAL in capsys.readouterr().err

    def test_binding_is_judged_against_the_resolved_root(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        # The tree pytest will collect from is the resolved repo root,
        # not the directory the caller happened to be standing in.
        seen: dict[str, object] = {}

        def _evaluate(**kwargs):
            seen.update(kwargs)
            return TreeBindingVerdict(refusal=REFUSAL)

        monkeypatch.setattr(
            run_tests.verification_tree_binding, "evaluate_run", _evaluate,
        )
        run_tests.run(["tests"], repo_root=tmp_path)
        assert seen["tree"] == str(tmp_path.resolve())
        assert seen["allow_mismatch"] is False

    def test_allow_flag_runs_and_prints_the_notice(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        launched: list[object] = []

        class _Proc:
            def wait(self) -> int:
                return 0

        def _popen(*args, **kwargs):
            launched.append(args)
            return _Proc()

        _bind(run_tests, monkeypatch, notice=NOTICE)
        monkeypatch.setattr(
            run_tests.process_group_reaping,
            "popen_in_process_group",
            _popen,
        )
        # A single existing file keeps the run out of the machine-wide
        # admission gate, which only throttles directory sweeps.
        target = tmp_path / "test_sample.py"
        target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        rc = run_tests.run(
            [str(target)], repo_root=tmp_path, allow_tree_mismatch=True,
        )
        assert rc == 0
        assert launched
        assert NOTICE in capsys.readouterr().err

    def test_cli_forwards_the_allow_flag(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen: dict[str, object] = {}

        def _run(paths, **kwargs):
            seen.update(kwargs)
            return 0

        monkeypatch.setattr(run_tests, "run", _run)
        run_tests.main(
            ["tests", verification_tree_binding.ALLOW_TREE_MISMATCH_FLAG],
        )
        assert seen["allow_tree_mismatch"] is True
