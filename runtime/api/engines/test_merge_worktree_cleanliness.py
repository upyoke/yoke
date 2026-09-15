"""Lane residue classification, including project-declared cache roots.

A fake ``run_git`` stands in for ``git status --porcelain --ignored=matching``
so these tests exercise the pure classification and (for ``clear_lane_residue``)
real filesystem removal without a real git repository.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Sequence

from yoke_core.engines.merge_worktree_cleanliness import (
    assess_lane_residue,
    clear_lane_residue,
)


class _FakeResult:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def _porcelain(ignored: Sequence[str] = (), precious: Sequence[str] = ()) -> str:
    lines = [f"!! {path}" for path in ignored]
    lines += [f" M {path}" for path in precious]
    return "\n".join(lines) + ("\n" if lines else "")


def _fake_git(stdout: str):
    def run_git(_args: list[str], cwd: Any = None, capture: bool = True) -> _FakeResult:
        return _FakeResult(stdout)

    return run_git


def test_declared_directory_root_covers_nested_generated_files(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    stdout = _porcelain(ignored=["docs/atlas.md", ".yoke/strategy/plan.md"])
    declared = frozenset(
        {PurePosixPath("docs/atlas.md"), PurePosixPath(".yoke/strategy")}
    )

    assessment = assess_lane_residue(_fake_git(stdout), tmp_path, declared)

    assert assessment.disposable
    assert set(assessment.cache_roots) == declared


def test_absent_declarations_preserve_existing_behavior(tmp_path: Path):
    """No declared roots means an undeclared ignored path stays unknown."""
    stdout = _porcelain(ignored=["docs/atlas.md"])

    assessment = assess_lane_residue(_fake_git(stdout), tmp_path)

    assert not assessment.disposable
    assert "unknown ignored files present" in assessment.reason


def test_unsafe_declaration_never_reaches_this_layer(tmp_path: Path):
    """The write-time validator refuses unsafe entries; this layer only sees
    already-validated roots, so an ordinary path outside the declared set
    still classifies as unknown rather than silently matching everything."""
    stdout = _porcelain(ignored=["docs/atlas.md", "some/other/ignored/file"])
    declared = frozenset({PurePosixPath("docs/atlas.md")})

    assessment = assess_lane_residue(_fake_git(stdout), tmp_path, declared)

    assert not assessment.disposable
    assert "some/other/ignored/file" in assessment.reason


def test_tracked_edit_still_blocks_despite_declared_roots(tmp_path: Path):
    stdout = _porcelain(
        ignored=["docs/atlas.md"], precious=["packages/yoke-core/src/thing.py"]
    )
    declared = frozenset({PurePosixPath("docs/atlas.md")})

    assessment = assess_lane_residue(_fake_git(stdout), tmp_path, declared)

    assert not assessment.disposable
    assert "unignored changes present" in assessment.reason


def test_clear_lane_residue_removes_declared_nested_content(tmp_path: Path):
    generated_dir = tmp_path / "nested" / "generated"
    generated_dir.mkdir(parents=True)
    (generated_dir / "output.json").write_text("{}")
    declared = frozenset({PurePosixPath("nested/generated")})

    # First status call (inside assess) reports the ignored dir; second call
    # (post-removal verification inside clear) reports a clean tree.
    calls = {"n": 0}

    def run_git(_args: list[str], cwd: Any = None, capture: bool = True) -> _FakeResult:
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResult(_porcelain(ignored=["nested/generated/"]))
        return _FakeResult("")

    assessment = clear_lane_residue(run_git, tmp_path, declared)

    assert assessment.disposable
    assert not generated_dir.exists()
