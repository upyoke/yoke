"""Project apply refuses checkout paths whose identity can redirect writes."""

from __future__ import annotations

from pathlib import Path

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

    rc = yoke_operations_cli.main([
        "project", "create", str(checkout),
        "--slug", "demo",
        "--name", "Demo",
        "--default-branch", "main",
        "--public-item-prefix", "DMO",
        "--config", str(tmp_path / "config.json"),
        "--yes",
    ])

    assert rc == 1
    assert "symbolic link" in capsys.readouterr().err
    assert sentinel.read_text(encoding="utf-8") == "operator data"
    assert not (victim / ".git").exists()
