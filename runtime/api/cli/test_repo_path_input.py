"""Windows-typed repo paths become POSIX repo-relative paths, or a named refusal."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from yoke_cli.commands.adapters import repo_path_input as paths
from yoke_cli.commands.adapters.claims_path_register_args import (
    PathRegisterArguments,
    parse_path_register_args,
)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "Repo"
    (root / "packages" / "app").mkdir(parents=True)
    (root / "packages" / "app" / "Main.py").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    return root


def test_posix_paths_pass_through_unchanged() -> None:
    typed = ["a\\b.py", "C:\\x\\y.py"]
    assert paths.normalize_repo_paths(typed, windows=False) == typed


def test_backslashes_become_forward_slashes(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    assert paths.normalize_repo_paths(
        ["packages\\app\\Main.py", " packages/app/Main.py "],
        repo_root=root,
        windows=True,
    ) == ["packages/app/Main.py", "packages/app/Main.py"]


def test_drive_letter_path_inside_repo_becomes_relative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(paths, "_repo_root", lambda root: "C:/Work/Repo")
    monkeypatch.setattr(paths, "_tracked_mismatches", lambda selected, root: [])

    assert paths.normalize_repo_paths(
        ["c:\\work\\repo\\packages\\app\\Main.py", "C:/Work/Repo/docs/a.md"],
        windows=True,
    ) == ["packages/app/Main.py", "docs/a.md"]


def test_drive_letter_path_outside_repo_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(paths, "_repo_root", lambda root: "C:/Work/Repo")

    with pytest.raises(paths.RepoPathInputError) as caught:
        paths.normalize_repo_paths(["D:\\other\\file.py"], windows=True)

    assert caught.value.code == "path_not_project_relative"
    assert "outside the repository" in str(caught.value)


def test_absolute_path_without_a_checkout_names_the_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(paths, "_repo_root", lambda root: None)

    with pytest.raises(paths.RepoPathInputError, match="relative to the repository"):
        paths.normalize_repo_paths(["C:\\x\\y.py"], windows=True)


@pytest.mark.parametrize(
    "typed",
    ["docs/CON", "docs/nul.txt", "lpt1/x.py", "docs/name.", "docs/name /x.py", "a/b:c.py"],
)
def test_reserved_windows_names_are_refused(typed: str, tmp_path: Path) -> None:
    with pytest.raises(paths.RepoPathInputError) as caught:
        paths.normalize_repo_paths([typed], repo_root=tmp_path, windows=True)

    assert caught.value.code == "path_windows_reserved"
    assert "Rename the file" in str(caught.value)


def test_paths_differing_only_by_case_are_refused(tmp_path: Path) -> None:
    with pytest.raises(paths.RepoPathInputError) as caught:
        paths.normalize_repo_paths(
            ["docs/Readme.md", "docs/README.md"], repo_root=tmp_path, windows=True
        )

    assert caught.value.code == "path_case_collision"
    assert "docs/README.md (matches docs/Readme.md)" in str(caught.value)


def test_path_cased_differently_from_tracked_file_names_the_spelling(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)

    with pytest.raises(paths.RepoPathInputError) as caught:
        paths.normalize_repo_paths(
            ["packages/app/main.py"], repo_root=root, windows=True
        )

    assert caught.value.code == "path_case_collision"
    assert "matches packages/app/Main.py" in str(caught.value)


def test_claim_register_sends_normalized_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setattr(paths, "_on_windows", lambda: True)

    parsed = parse_path_register_args(
        ["--item", "YOK-1", "--paths", "packages\\app\\Main.py"]
    )

    assert isinstance(parsed, PathRegisterArguments)
    assert parsed.payload["paths"] == ["packages/app/Main.py"]


def test_claim_register_refuses_reserved_name_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paths, "_on_windows", lambda: True)

    code = parse_path_register_args(
        ["--item", "YOK-1", "--paths", "aux.py", "--allow-planned"]
    )

    assert code == 2
    assert "path_windows_reserved" in capsys.readouterr().err
