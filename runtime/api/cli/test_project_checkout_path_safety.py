"""Project apply refuses checkout paths whose identity can redirect writes."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_cli import main as yoke_operations_cli


def test_project_apply_refuses_replaced_symlink_checkout(
    tmp_path: Path,
    capsys,
) -> None:
    victim = tmp_path / "operator-home"
    victim.mkdir()
    sentinel = victim / "keep.txt"
    sentinel.write_text("operator data", encoding="utf-8")
    checkout = tmp_path / "project"
    checkout.symlink_to(victim, target_is_directory=True)

    (tmp_path / "config.json").write_text("{}\n", encoding="utf-8")
    rc = yoke_operations_cli.main(
        [
            "project",
            "create",
            str(checkout),
            "--slug",
            "demo",
            "--name",
            "Demo",
            "--default-branch",
            "main",
            "--public-item-prefix",
            "DMO",
            "--config",
            str(tmp_path / "config.json"),
            "--yes",
        ]
    )

    assert rc == 1
    assert "symbolic link" in capsys.readouterr().err
    assert sentinel.read_text(encoding="utf-8") == "operator data"
    assert not (victim / ".git").exists()


def test_path_under_a_file_names_the_file(tmp_path: Path) -> None:
    from yoke_cli.config.project_checkout_path import validation_error

    blocker = tmp_path / "passwd"
    blocker.write_text("not a folder", encoding="utf-8")
    assert validation_error(blocker / "qa-proj" / "deeper") == (
        f"{blocker} is a file, not a folder — pick a folder path."
    )


@pytest.mark.posix_only(reason="/etc/passwd is a POSIX file")
def test_etc_passwd_child_names_etc_passwd() -> None:
    from yoke_cli.config.project_checkout_path import validation_error

    assert validation_error("/etc/passwd/qa-proj") == (
        "/etc/passwd is a file, not a folder — pick a folder path."
    )
