"""Rendered-source attribution and stray-working-tree refusal for Pulumi exec."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
import subprocess

import pytest

from runtime.api.tools.test_pulumi_exec_support import (
    _Child,
    _install_pulumi_project_files,
    _stack_payload,
)
from yoke_core.tools.pulumi_exec import PulumiExecError, execute_pulumi_command
from yoke_core.tools.pulumi_exec_source import (
    announce_render_source,
    resolve_render_source,
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _checkout(root: Path, name: str = "checkout") -> tuple[Path, str]:
    """Build a committed checkout carrying one Pulumi program file."""
    repo = root / name
    (repo / "infra").mkdir(parents=True)
    _git_init(repo)
    (repo / "infra" / "__main__.py").write_text("program\n", encoding="utf-8")
    _git(repo, "add", "infra/__main__.py")
    _git(repo, "commit", "-m", "program")
    return repo, _git(repo, "rev-parse", "HEAD")


def _git_init(repo: Path) -> None:
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


def test_committed_checkout_reports_its_path_revision_and_clean_program(
    tmp_path: Path,
) -> None:
    repo, head = _checkout(tmp_path)

    source = resolve_render_source(repo)

    assert source.checkout == repo.resolve()
    assert source.revision == head
    assert source.uncommitted == 0
    assert str(repo.resolve()) in source.description
    assert head[:12] in source.description
    assert "infra/ clean" in source.description


def test_uncommitted_program_changes_are_counted_and_named(
    tmp_path: Path,
) -> None:
    repo, _head = _checkout(tmp_path)
    (repo / "infra" / "__main__.py").write_text("changed\n", encoding="utf-8")
    (repo / "infra" / "extra.py").write_text("added\n", encoding="utf-8")

    source = resolve_render_source(repo)

    assert source.uncommitted == 2
    assert "2 uncommitted change(s) in infra/" in source.description


def test_changes_outside_the_program_directory_do_not_count(
    tmp_path: Path,
) -> None:
    repo, _head = _checkout(tmp_path)
    (repo / "unrelated.txt").write_text("noise\n", encoding="utf-8")

    assert resolve_render_source(repo).uncommitted == 0


def test_a_directory_outside_git_says_the_revision_is_unavailable(
    tmp_path: Path,
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    source = resolve_render_source(plain)

    assert source.repository == ""
    assert source.revision == ""
    assert "not a git checkout" in source.description


def test_announcement_names_the_source_before_anything_else_runs(
    tmp_path: Path,
) -> None:
    repo, head = _checkout(tmp_path)
    err = StringIO()

    announce_render_source(repo, caller_root=repo, err=err)

    written = err.getvalue()
    assert written.startswith("yoke pulumi exec: rendering ")
    assert str(repo.resolve()) in written
    assert head[:12] in written


def test_a_sibling_worktree_of_the_same_repository_is_refused(
    tmp_path: Path,
) -> None:
    repo, head = _checkout(tmp_path)
    lane = tmp_path / "lane"
    _git(repo, "worktree", "add", "--detach", str(lane), head)
    err = StringIO()

    with pytest.raises(PulumiExecError) as refusal:
        announce_render_source(repo, caller_root=lane, err=err)

    message = str(refusal.value)
    assert str(repo.resolve()) in message
    assert str(lane.resolve()) in message
    assert "same repository, a different working tree" in message
    assert "yoke project register" in message
    assert err.getvalue() == ""


def test_a_caller_in_an_unrelated_repository_still_renders(
    tmp_path: Path,
) -> None:
    repo, _head = _checkout(tmp_path)
    other, _other_head = _checkout(tmp_path, name="other-project")
    err = StringIO()

    source = announce_render_source(repo, caller_root=other, err=err)

    assert source.checkout == repo.resolve()
    assert "yoke pulumi exec: rendering " in err.getvalue()


def test_a_caller_outside_any_working_tree_still_renders(
    tmp_path: Path,
) -> None:
    repo, _head = _checkout(tmp_path)
    err = StringIO()

    source = announce_render_source(repo, caller_root=None, err=err)

    assert source.checkout == repo.resolve()
    assert "yoke pulumi exec: rendering " in err.getvalue()


def test_preview_states_its_source_alongside_the_child_result(
    tmp_path: Path,
) -> None:
    project_root = _install_pulumi_project_files(tmp_path)
    _git_init(project_root)
    _git(project_root, "add", "--all")
    _git(project_root, "commit", "-m", "installed")
    head = _git(project_root, "rev-parse", "HEAD")
    out = StringIO()
    err = StringIO()

    result = execute_pulumi_command(
        "externalwebapp",
        "externalwebapp-registry",
        ["preview", "--non-interactive"],
        config_loader=lambda project, stack: _stack_payload(project, stack),
        project_root=project_root,
        caller_root=project_root,
        aws_env_loader=lambda *args, **kwargs: {},
        child_factory=lambda command, **kwargs: _Child(b"preview-ok\n"),
        out=out,
        err=err,
    )

    assert result == 0
    assert out.getvalue() == "preview-ok\n"
    assert f"rendering {project_root.resolve()} @ {head[:12]}" in err.getvalue()


def test_a_stray_working_tree_refuses_before_any_stack_is_read(
    tmp_path: Path,
) -> None:
    project_root = _install_pulumi_project_files(tmp_path)
    _git_init(project_root)
    _git(project_root, "add", "--all")
    _git(project_root, "commit", "-m", "installed")
    head = _git(project_root, "rev-parse", "HEAD")
    lane = tmp_path / "lane"
    _git(project_root, "worktree", "add", "--detach", str(lane), head)

    def refuse_config(project: str, stack: str):
        raise AssertionError("the stack config must not be read after a refusal")

    with pytest.raises(PulumiExecError, match="different working tree"):
        execute_pulumi_command(
            "externalwebapp",
            "externalwebapp-registry",
            ["preview", "--non-interactive"],
            config_loader=refuse_config,
            project_root=project_root,
            caller_root=lane,
            child_factory=_unreachable_child,
            out=StringIO(),
            err=StringIO(),
        )


def _unreachable_child(command, **kwargs):
    raise AssertionError("no Pulumi child may run for a refused working tree")
