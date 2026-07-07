"""Project-local file-line policy coverage for core and product checkers."""

from __future__ import annotations

import pathlib

from yoke_core.domain import file_line_check as core_gate
from yoke_harness.git_hooks import file_line_check as harness_gate


def _write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _lines(count: int) -> str:
    return "\n".join(f"x{i}" for i in range(count)) + "\n"


def test_project_exception_file_is_used_by_both_checkers(tmp_path: pathlib.Path) -> None:
    _write(tmp_path / ".yoke" / "file-line-exceptions", "data/big.txt\n")
    _write(tmp_path / "data" / "big.txt", _lines(800))

    assert (
        core_gate.classify_path("data/big.txt", repo_root=tmp_path)
        == core_gate.Classification.TEMPORARY_EXCEPTION
    )
    assert (
        harness_gate.classify_path("data/big.txt", repo_root=tmp_path)
        == harness_gate.Classification.TEMPORARY_EXCEPTION
    )


def test_local_policy_limit_uses_source_default(tmp_path: pathlib.Path) -> None:
    assert core_gate.resolved_policy(tmp_path).limit == core_gate.LIMIT
    assert harness_gate.resolved_policy(tmp_path).limit == harness_gate.LIMIT
