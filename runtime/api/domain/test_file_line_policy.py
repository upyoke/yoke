"""Project-local file-line policy coverage for core and product checkers."""

from __future__ import annotations

import pathlib

from yoke_core.domain import file_line_check as core_gate
from yoke_harness.git_hooks import file_line_check as harness_gate


def _write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _config(repo: pathlib.Path, text: str) -> None:
    _write(repo / ".yoke" / "project.config", text)


def _lines(count: int) -> str:
    return "\n".join(f"x{i}" for i in range(count)) + "\n"


def test_project_exception_glob_is_used_by_both_checkers(
    tmp_path: pathlib.Path,
) -> None:
    _config(tmp_path, "file_line_exception=data/big.txt\n")
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


def test_limit_key_is_honored_by_both_checkers(tmp_path: pathlib.Path) -> None:
    """The offline hook and the source-dev checker read one limit.

    A database-owned limit could not be honored by a pre-commit hook
    running in a fresh clone, so the limit rides the repo in the same
    config file as its exception globs.
    """
    _config(
        tmp_path,
        "# policy\nfile_line_limit=500\nfile_line_exception=data/big.txt\n",
    )

    assert core_gate.resolved_policy(tmp_path).limit == 500
    assert harness_gate.resolved_policy(tmp_path).limit == 500


def test_limit_key_is_not_read_as_an_exception_glob(
    tmp_path: pathlib.Path,
) -> None:
    _config(
        tmp_path,
        "file_line_limit=500\nfile_line_exception=data/big.txt\n",
    )

    for gate in (core_gate, harness_gate):
        globs = gate.resolved_policy(tmp_path).exception_globs
        assert "data/big.txt" in globs
        assert not any("file_line_limit" in glob for glob in globs)


def test_installer_rendered_adapters_are_generated_without_a_manifest(
    tmp_path: pathlib.Path,
) -> None:
    """Classification must not depend on the gitignored install manifest.

    A fresh clone or CI runner has no `.yoke/install-manifest.json`. When
    the verdict was derived from it, the same commit classified generated
    on an installed checkout and authored in CI — a gate that disagrees
    with itself by environment. Tracked path shape is the authority.
    """
    _write(tmp_path / ".claude" / "agents" / "yoke-engineer.md", _lines(800))
    _write(tmp_path / ".codex" / "agents" / "yoke-engineer.toml", _lines(800))
    assert not (tmp_path / ".yoke" / "install-manifest.json").exists()

    for gate in (core_gate, harness_gate):
        for rendered in (
            ".claude/agents/yoke-engineer.md",
            ".codex/agents/yoke-engineer.toml",
        ):
            assert (
                gate.classify_path(rendered, repo_root=tmp_path)
                == gate.Classification.GENERATED
            ), (gate.__name__, rendered)


def test_unusable_limit_falls_back_to_default(tmp_path: pathlib.Path) -> None:
    """A typo must never silently relax the limit."""
    for raw in ("not-a-number", "0", "-10", ""):
        _config(tmp_path, f"file_line_limit={raw}\n")
        assert core_gate.resolved_policy(tmp_path).limit == core_gate.LIMIT
        assert harness_gate.resolved_policy(tmp_path).limit == harness_gate.LIMIT
