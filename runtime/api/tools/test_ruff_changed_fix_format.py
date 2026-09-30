"""Coverage for writing formatting over the changed-path set.

``--format-check`` reports the reformatting a commit would need; ``--fix-format``
performs it. The ordering is the contract worth pinning: formatting is written
before the lint runs, because a formatter rewrite can itself introduce or clear
a lint diagnostic, and the result a caller acts on has to describe the bytes
their commit will carry.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_contracts.project_contract.changed_path_scope import (
    WorkingTreeChangedPaths,
)
from yoke_core.tools import ruff_changed


def _one_changed_module(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ruff_changed,
        "select_changed_python_paths",
        lambda _base, _root: ruff_changed.ChangedPythonSelection(
            ("module.py",),
            "base-sha",
            "head-sha",
            WorkingTreeChangedPaths(tracked=("module.py",), untracked=()),
        ),
    )


def _recording_ruff(
    monkeypatch: pytest.MonkeyPatch,
    statuses: dict[tuple[str, ...], int] | None = None,
) -> list[tuple[str, ...]]:
    phases: list[tuple[str, ...]] = []

    def _record(
        _root: Path,
        arguments: tuple[str, ...],
        _paths: tuple[str, ...],
    ) -> int:
        phases.append(arguments)
        return (statuses or {}).get(arguments, 0)

    monkeypatch.setattr(ruff_changed, "_run_ruff", _record)
    return phases


def test_fix_format_writes_formatting_before_linting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _one_changed_module(monkeypatch)
    phases = _recording_ruff(monkeypatch)

    assert ruff_changed.run("main", fix_format=True, root=tmp_path) == 0
    assert phases == [("format",), ("check",)]


def test_fix_format_never_runs_the_format_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _one_changed_module(monkeypatch)
    phases = _recording_ruff(monkeypatch)

    ruff_changed.run("main", fix_format=True, root=tmp_path)
    assert ("format", "--check") not in phases


def test_fix_format_covers_the_same_paths_the_lint_covers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Formatting a narrower set than CI checks would leave a gap behind a
    green, so both phases receive one selection."""
    monkeypatch.setattr(
        ruff_changed,
        "select_changed_python_paths",
        lambda _base, _root: ruff_changed.ChangedPythonSelection(
            ("tracked.py", "untracked.py"),
            "base-sha",
            "head-sha",
            WorkingTreeChangedPaths(
                tracked=("tracked.py",), untracked=("untracked.py",)
            ),
        ),
    )
    seen: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    def _record(
        _root: Path,
        arguments: tuple[str, ...],
        paths: tuple[str, ...],
    ) -> int:
        seen.append((arguments, paths))
        return 0

    monkeypatch.setattr(ruff_changed, "_run_ruff", _record)

    assert ruff_changed.run("main", fix_format=True, root=tmp_path) == 0
    assert seen == [
        (("format",), ("tracked.py", "untracked.py")),
        (("check",), ("tracked.py", "untracked.py")),
    ]


def test_failed_format_write_stops_before_linting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _one_changed_module(monkeypatch)
    phases = _recording_ruff(monkeypatch, {("format",): 2})

    assert ruff_changed.run("main", fix_format=True, root=tmp_path) == 2
    assert phases == [("format",)]
    assert "no formatting was applied" in capsys.readouterr().err


def test_empty_changed_set_writes_no_formatting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        ruff_changed,
        "select_changed_python_paths",
        lambda _base, _root: ruff_changed.ChangedPythonSelection(
            (),
            "base-sha",
            "head-sha",
            WorkingTreeChangedPaths(tracked=(), untracked=()),
        ),
    )
    monkeypatch.setattr(
        ruff_changed,
        "_run_ruff",
        lambda *_a, **_k: pytest.fail("an empty selection must invoke no Ruff"),
    )

    assert ruff_changed.run("main", fix_format=True, root=tmp_path) == 0


def test_fix_format_result_names_the_formatting_it_wrote(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _one_changed_module(monkeypatch)
    _recording_ruff(monkeypatch)

    ruff_changed.run("main", fix_format=True, root=tmp_path)
    assert "commit the formatting this wrote" in capsys.readouterr().out


def test_fix_format_and_format_check_cannot_be_combined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One reports the reformatting and one performs it, so asking for both is
    an unresolved intent argparse refuses rather than silently ranking."""
    monkeypatch.setattr(
        ruff_changed,
        "resolve_tree",
        lambda _workdir: pytest.fail("parsing must refuse before resolving a tree"),
    )
    with pytest.raises(SystemExit) as raised:
        ruff_changed.main(["--base", "main", "--format-check", "--fix-format"])
    assert raised.value.code == 2


def test_fix_format_reaches_run_from_the_command_line(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(ruff_changed, "resolve_tree", lambda _workdir: (tmp_path, None))
    monkeypatch.setattr(
        ruff_changed,
        "run",
        lambda base, **kwargs: captured.update({"base": base, **kwargs}) or 0,
    )

    assert ruff_changed.main(["--base", "main", "--fix-format"]) == 0
    assert captured["fix_format"] is True
    assert captured["format_check"] is False


def test_usage_names_the_flag() -> None:
    from yoke_cli.commands.tool_shaped import TOOL_SHAPED_USAGE

    assert "--fix-format" in TOOL_SHAPED_USAGE["yoke dev ruff-changed"]
