"""Unit tests for ``reconcile_gitignore`` — the install/refresh backfill that
brings an existing ``.yoke/.gitignore`` up to the canonical ignore set (the
seed-if-missing apply never touches an already-present file)."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from yoke_cli.project_install.files import apply_contract_files, reconcile_gitignore
from yoke_core.domain import project_contract

_CANONICAL = {
    "path": ".yoke/.gitignore",
    "content": "# header comment\nBOARD.md\nbackups/\nstrategy/\n.merge-lock\n",
}


def _write(root: Path, body: str) -> Path:
    target = root / ".yoke/.gitignore"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


def test_appends_missing_canonical_lines(tmp_path: Path) -> None:
    target = _write(tmp_path, "# old header\nBOARD.md\nbackups/\ncustom-line\n")
    appended = reconcile_gitignore(tmp_path, [_CANONICAL])
    assert set(appended) == {"strategy/", ".merge-lock"}
    after = target.read_text(encoding="utf-8")
    # Missing canonical lines added; operator-added line preserved.
    assert "strategy/" in after and ".merge-lock" in after
    assert "custom-line" in after


def test_idempotent_second_run(tmp_path: Path) -> None:
    _write(tmp_path, "# h\nBOARD.md\nbackups/\ncustom-line\n")
    reconcile_gitignore(tmp_path, [_CANONICAL])
    assert reconcile_gitignore(tmp_path, [_CANONICAL]) == []


def test_absent_file_is_a_noop(tmp_path: Path) -> None:
    # Seed-if-missing owns first write; reconcile only touches an existing file.
    assert reconcile_gitignore(tmp_path, [_CANONICAL]) == []
    assert not (tmp_path / ".yoke/.gitignore").exists()


def test_already_complete_is_a_noop(tmp_path: Path) -> None:
    _write(tmp_path, "# h\nBOARD.md\nbackups/\nstrategy/\n.merge-lock\n")
    assert reconcile_gitignore(tmp_path, [_CANONICAL]) == []


def test_no_gitignore_entry_in_bundle_is_a_noop(tmp_path: Path) -> None:
    _write(tmp_path, "BOARD.md\n")
    assert reconcile_gitignore(tmp_path, [{"path": ".yoke/README.md", "content": "x"}]) == []


@pytest.mark.parametrize("existing_install", [False, True])
def test_strategy_guidance_tracks_while_rendered_views_stay_ignored(
    tmp_path: Path, existing_install: bool
) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    entry = next(
        entry
        for entry in project_contract.bundle_contract_files("Acme")
        if entry["path"] == ".yoke/.gitignore"
    )
    if existing_install:
        _write(tmp_path, "# existing policy\nstrategy/\ncustom-pattern\n")
    apply_contract_files(tmp_path, [entry], {})
    reconcile_gitignore(tmp_path, [entry])

    for relative, ignored in (
        (".yoke/strategy/CURRENT-PLAN.md", True),
        (".yoke/strategy/archive/PRIOR.md", True),
        (".yoke/docs/strategy/index.md", False),
        (".yoke/docs/strategy/charge-frontier.md", False),
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("Guidance or rendered direction.\n", encoding="utf-8")
        result = subprocess.run(
            ["git", "-C", str(tmp_path), "check-ignore", relative],
            capture_output=True,
        )
        assert result.returncode == (0 if ignored else 1), relative

    subprocess.run(
        ["git", "-C", str(tmp_path), "add", ".yoke/docs/strategy"],
        check=True,
        capture_output=True,
    )
    tracked = subprocess.run(
        ["git", "-C", str(tmp_path), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert tracked == [
        ".yoke/docs/strategy/charge-frontier.md",
        ".yoke/docs/strategy/index.md",
    ]
    if existing_install:
        assert "custom-pattern" in (tmp_path / entry["path"]).read_text()
    assert reconcile_gitignore(tmp_path, [entry]) == []
